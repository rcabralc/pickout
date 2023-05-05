# These optimizations were got from
# https://suzyahyah.github.io/cython/programming/2018/12/01/Gotchas-in-Cython.html

#cython: boundscheck=False
#cython: nonecheck=False
#cython: wraparound=False
#cython: infertypes=True
#cython: initializedcheck=False
#cython: cdivision=True

#cython: language_level=3

import array
import heapq
import operator
import re
import sre_constants
import sys
import unicodedata

from cython.view cimport array as cvarray
from cpython cimport array
from itertools import chain
from libc.string cimport memset


# Stuff used for fuzzy matching.
cdef int MIN_SCORE = -2**31 + 1 # make room for subtracting 1 without overflow
cdef int CONSECUTIVE_SCORE = 50
cdef int WORD_START_SCORE = 10
cdef int PATTERN_GLOBAL_MAX_LENGTH = 64
cdef int ENTRY_GLOBAL_MAX_LENGTH = 256
cdef array.array empty = array.array('i', [])
cdef int [::1] cempty = empty
cdef enum CharType: word_start, regular


cdef int [:,:,:] create_fuzzy_search_data(int p_length, int v_length):
    return cvarray(shape=(2, p_length, v_length + 1),
                   itemsize=sizeof(int),
                   format='i')
cdef int [:,:,:] GLOBAL_M = create_fuzzy_search_data(PATTERN_GLOBAL_MAX_LENGTH,
                                                     ENTRY_GLOBAL_MAX_LENGTH)


cdef class Entry:
    cdef public int index
    cdef public str id
    cdef public str value
    cdef public str civalue
    cdef public int length
    cdef public int[::1] char_types
    cdef dict _data

    def __init__(self, int index, str value not None, str id = None, dict data = None):
        cdef int i, l

        self.index = index
        value = unicodedata.normalize('NFKD', value)
        self.value = value
        self.id = id if id is not None else value
        self.civalue = value if value.islower() else value.lower()
        self.length = l = len(value)
        self._data = data
        if l:
            self.char_types = cvarray(shape=(l,),
                                      itemsize=sizeof(int),
                                      format='i')
            for i in range(l):
                if (
                    # word delimiters
                    i == 0 or value[i - 1] in '*._-/{[( ' or
                    # uppercase following lowercase, like 'w' in 'thisWord'
                    (value[i].isupper() and value[i - 1].islower())
                ):
                    self.char_types[i] = word_start
                else:
                    self.char_types[i] = regular

    @property
    def data(self):
        return self._data if self._data is not None else {}

    def as_json(self):
        return dict(id=self.id, value=self.value, data=self.data)


class Pattern:
    def __init__(self, pattern):
        self.value = unicodedata.normalize('NFKD', pattern)
        self.length = len(pattern) if pattern else 0

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return self.value == other.value
        return False

    def __hash__(self):
        return hash(self.value)

    def __len__(self):
        return self.length

    def __bool__(self):
        return self.length > 0


class SmartCasePattern(Pattern):
    def __init__(self, pattern):
        super(SmartCasePattern, self).__init__(pattern)

        pattern_lower = self.value.lower()

        if pattern_lower != self.value:
            self.ignore_case = False
        else:
            self.value = pattern_lower
            self.ignore_case = True


cdef class FuzzyPattern:
    cdef public str value
    cdef public int length
    cdef public bint ignore_case

    prefix = '@*'

    def __init__(self, str pattern):
        cdef str pattern_lower
        cdef int p_length

        value = unicodedata.normalize('NFKD', pattern)

        if value:
            p_length = self.length = len(value)
        else:
            p_length = self.length = 0

        pattern_lower = value.lower()

        if pattern_lower != value:
            self.value = value
            self.ignore_case = False
        else:
            self.value = pattern_lower
            self.ignore_case = True

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return self.value == other.value
        return False

    def __hash__(self):
        return hash(self.value)

    def __len__(self):
        return self.length

    def __bool__(self):
        return self.length > 0

    def __contains__(self, other):
        if self.length == 0:
            return True

        if isinstance(other, type(self)):
            if not self.ignore_case and other.ignore_case:
                return False
            return self.match(Entry(0, other.value)) is not None

        return False

    def __repr__(self):
        return f'<FuzzyPattern {self.value!r}>'

    # Fuzzy matching largely inspired by fzy.
    # https://github.com/jhawthorn/fzy
    # Using different weights for matching and a different strategy for
    # backtracing.
    cdef Match match(self, Entry entry, int [:,:,:] m=None):
        cdef int p_length = self.length
        cdef Match match

        if p_length == 0:
            return Match.empty()

        cdef int v_length = entry.length
        cdef int r_limit = v_length - p_length + 1
        cdef int l_limit = 0
        cdef int pi, vi, prev_vi, score, best_score = MIN_SCORE, best_idx
        cdef int prev_score, match_score
        cdef str value, pattern
        cdef Py_UCS4 p
        cdef int[::1] indices

        value = entry.civalue if self.ignore_case else entry.value
        pattern = self.value

        # m[X, Y, Z] stores the matching results
        # X = 0:1, 0 = best score, 1 = score if ending in the position
        # Y = 0:p_length-1, Z = 0:v_length-1 is the matrix of scores
        # in X=0, Z = v_length the first match index is stored for later
        # backtracing.
        # in X=1, Z = v_length, the best score index is stored, useful to jump
        # to the best score when starting backtracing.
        if m is None:
            m = create_fuzzy_search_data(p_length, v_length)

        for pi in range(p_length):
            p = pattern[pi]
            prev_score = best_score = MIN_SCORE
            for vi in range(l_limit, r_limit):
                if value[vi] == p:
                    prev_vi = vi - 1
                    # Record start index and bump l_limit.
                    if best_score == MIN_SCORE:
                        m[0, pi, v_length] = l_limit = vi
                    if entry.char_types[vi] == CharType.word_start:
                        score = WORD_START_SCORE
                    else:
                        score = 1
                    if pi != 0:
                        score += m[0, pi - 1, prev_vi]
                        if m[1, pi - 1, prev_vi] + CONSECUTIVE_SCORE > score:
                            score = m[1, pi - 1, prev_vi] + CONSECUTIVE_SCORE
                else:
                    if best_score == MIN_SCORE: continue
                    score = MIN_SCORE

                m[1, pi, vi] = score
                if prev_score - 1 > score:
                    score = prev_score - 1
                m[0, pi, vi] = prev_score = score
                if score >= best_score: # >= because we want rightmost best.
                    m[1, pi, v_length] = vi
                    best_score = score
            # If we didn't improve best score, we failed to find a match for
            # `p`.
            if best_score == MIN_SCORE: return
            r_limit += 1
            l_limit += 1

        match_score = best_score
        indices = cvarray(shape=(p_length,), itemsize=sizeof(int), format='i')
        memset(&indices[0], 0, p_length * sizeof(int))
        best_idx = m[1, p_length - 1, v_length]
        indices[p_length - 1] = best_idx
        for pi in range(p_length - 2, -1, -1):
            vi = best_idx - 1
            # Prefer to show a consecutive match if the score ending here is
            # the same as if it were not a match.  The final resulting score
            # would have been the same.
            if m[1, pi, vi] == m[0, pi, vi] and pattern[pi] == value[vi]:
                indices[pi] = best_idx = vi
                continue
            # Look for the best index, stop looking if score starts decreasing.
            # Might not find the best perfect match, as there are multiple
            # possible ways, but stopping early won't hurt.
            best_score = MIN_SCORE
            # Check only until start index, because after that numbers weren't
            # initialized.
            for vi in range(vi, m[0, pi, v_length] - 1, -1):
                score = m[0, pi, vi]
                if score <= best_score: break
                best_score = score
                best_idx = vi
            indices[pi] = best_idx

        # Match takes a rank for its first argument.  The lower the better.
        return Match.present(v_length - match_score, indices)


class RegexPattern(Pattern):
    prefix = '@/'

    def __init__(self, pattern, ignore_bad_patterns=True):
        super(RegexPattern, self).__init__(pattern)
        self._can_match = False
        if pattern:
            self.value = '(?iu)' + pattern
            self._can_match = True
            try:
                self._re = re.compile(self.value)
            except sre_constants.error:
                if not ignore_bad_patterns:
                    raise
                self._can_match = False

    def __contains__(self, _other):
        return False

    def __repr__(self):
        return f'<RegexPattern {self.value!r}>'

    def match(self, entry, **_kw):
        if not self._can_match:
            return Match.empty()

        value = entry.value
        match = self._re.search(value)
        if match is not None:
            min, max = match.span()
            length = max - min
            indices = cvarray(shape=(length,), itemsize=sizeof(int), format='i')
            for i, mi in enumerate(range(min, max)):
                indices[i] = mi
            return Match.present(length, indices)


cdef class CompositePattern:
    cdef list _patterns

    def __cinit__(self, patterns):
        self._patterns = patterns

    cdef CompositeMatch match(self, Entry entry, int [:,:,:] global_m=None):
        cdef Match match
        cdef FuzzyPattern fuzzy_pattern
        cdef list matches = []
        cdef list patterns = self._patterns
        cdef int i
        cdef int [:,:,:] pattern_m

        if entry.length > ENTRY_GLOBAL_MAX_LENGTH:
            global_m = None

        for i in range(len(patterns)):
            pattern = patterns[i]

            if pattern.length > PATTERN_GLOBAL_MAX_LENGTH:
                pattern_m = None
            else:
                pattern_m = global_m

            if isinstance(pattern, FuzzyPattern):
                fuzzy_pattern = pattern
                match = fuzzy_pattern.match(entry, m=pattern_m)
            else:
                match = pattern.match(entry, m=pattern_m)

            if match is None:
                return

            matches.append(match)

        return CompositeMatch.c(entry, matches)


cdef class Match:
    cdef public int rank
    cdef public int[::1] indices

    @staticmethod
    cdef Match empty():
        cdef Match match
        match = Match.__new__(Match)
        match.rank = 0
        match.indices = cempty
        return match

    @staticmethod
    cdef Match present(int rank, int [::1] indices):
        cdef Match match
        match = Match.__new__(Match)
        match.rank = rank
        match.indices = indices
        return match


cdef class CompositeMatch:
    cdef public Entry entry
    cdef public tuple rank
    cdef list _matches

    @staticmethod
    cdef c(Entry entry, list matches):
        cdef CompositeMatch match = CompositeMatch.__new__(CompositeMatch)
        match.entry = entry
        match.rank = (sum(m.rank for m in matches), len(entry.value),
                      entry.value)
        match._matches = matches
        return match

    def as_json(self):
        return dict(rank=self.rank, partitions=self.partitions, entry=self.entry)

    @property
    def partitions(self):
        return self._partitions(self._matches)

    def _partitions(self, list matches not None):
        cdef Match first_match
        cdef set indices
        cdef int length = len(matches)

        if length == 0:
            return [dict(unmatched=self.entry.value, matched='')]

        if length == 1:
            return list(Chunks.c(matches[0].indices, self.entry))

        first_match, *other_matches = matches
        indices = set(first_match.indices)
        for match in other_matches:
            indices.update(match.indices)
        return list(Chunks.c(array.array('i', sorted(indices)), self.entry))


cdef class Chunks:
    cdef int [::1] _indices
    cdef str _value

    @staticmethod
    cdef c(int [::1] indices, Entry entry):
        cdef Chunks chunks = Chunks.__new__(Chunks)
        chunks._indices = indices
        chunks._value = entry.value
        return chunks

    def __iter__(self):
        cdef int i = 0
        cdef int last_end = 0
        cdef int [::1] indices = self._indices
        cdef str value = self._value
        cdef str unmatched
        cdef str matched
        cdef int len_indices = len(indices)

        if len_indices:
            while i < len_indices:
                t = indices[i]
                unmatched = value[last_end:t]
                while i + 1 < len_indices and indices[i + 1] == indices[i] + 1:
                    i += 1
                last_end = indices[i] + 1
                matched = value[t:last_end]
                yield dict(unmatched=unmatched, matched=matched)
                i += 1
        if last_end < len(value):
            yield dict(unmatched=value[last_end:], matched='')


class Filter:
    def __init__(self, entries, *patterns, ignore_bad_patterns=True, pool=None):
        patterns = [
            type(self).build_pattern(p, ignore_bad_patterns=ignore_bad_patterns)
            for p in patterns
        ]
        self._entries = entries
        self._pattern = CompositePattern(list(patterns))
        self.pool = pool

    def __iter__(self):
        if not self.pool:
            return iter(_get_matches(self._entries, self._pattern))

        entries = list(self._entries)
        batches = []
        size = len(entries) // 4
        for n in range(3):
            batches.append([entries[n * size:(n + 1) * size], self._pattern])
        batches.append([entries[3 * size:], self._pattern])
        results = [batch for batch in batches if batch[0]]
        return chain(*self.pool.map(_filter, results))

    @classmethod
    def build_pattern(self, pattern, ignore_bad_patterns=True):
        patternTypes = (
            FuzzyPattern,
            RegexPattern,
        )
        if isinstance(pattern, Pattern) or isinstance(pattern, FuzzyPattern):
            return pattern
        for patternType in patternTypes:
            if pattern.startswith(patternType.prefix):
                if patternType == RegexPattern:
                    return patternType(pattern[len(patternType.prefix):],
                                       ignore_bad_patterns=ignore_bad_patterns)
                return patternType(pattern[len(patternType.prefix):])
        return FuzzyPattern(pattern)


class Ranking:
    def __init__(self, matches, limit=None, reverse=False):
        self._matches = matches
        self._limit = limit
        self._reverse = reverse

    def __iter__(self):
        key = operator.attrgetter('rank')

        if self._limit is None:
            return iter(sorted(self._matches, key=key, reverse=self._reverse))
        elif self._reverse:
            return iter(heapq.nlargest(self._limit, self._matches, key=key))
        return iter(heapq.nsmallest(self._limit, self._matches, key=key))


def _filter(job):
    cdef tuple entries = job[0]
    cdef CompositePattern pattern = job[1]
    cdef int [:,:,:] m = create_fuzzy_search_data(PATTERN_GLOBAL_MAX_LENGTH,
                                                  ENTRY_GLOBAL_MAX_LENGTH)
    return tuple(_get_matches(entries, pattern, global_m=m))


def _get_matches(entries, CompositePattern pattern not None,
                 int [:,:,:] global_m=GLOBAL_M):
    cdef Entry entry
    cdef CompositeMatch match
    for entry in entries:
        match = pattern.match(entry, global_m=global_m)
        if match is not None:
            yield match
