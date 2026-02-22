#!/usr/bin/env python
"""Pickout.

Usage:
    pickout [--accept-query]
            [--big-word-delimiters=<delimiters>]
            [--completion-sep=<sep>]
            [--debug]
            [--history-key=<key>]
            [--home-query=<query>]
            [--initial-query=<query>]
            [--json-input]
            [--json-output]
            [--limit=<limit>]
            [--prompt=<prompt>]
            [--source=<command>]
            [--word-delimiters=<delimiters>]
            [--qwindowgeometry=<geometry>]
            [--qwindowtitle=<title>]

Options:
    --accept-query
        Allow any text typed in the query box to be accepted through Ctrl-Enter.

    --big-word-delimiters <delimiters>
        Delimiters used for "big" words. Any delimiter here is also considered a
        normal word delimiter. See --word-delimiters and Key Bindings section.

        Whitespace is always considered a big word delimiter.

    --completion-sep <sep>
        Separator used for completion.  Without this, completion works by
        completing longest common match.  This can be used to complete only
        directories in a list of files, for instance: use '/' (or OS path
        separator) for this.

    --debug
        Print additional information to STDERR.

    --history-key <key>
        A key which must be unique to store/retrieve history.  Any string can
        be used.  History is enabled only if this option is provided and is not
        empty.

        For instance, if listing all files under a specific directory, use that
        directory as the key.  Next time this program is used for this
        directory, it'll remember the previous queries, allowing the user to
        reuse it.

    --home-query <query>
        Defines an query to be the "home" query (set by pressing Ctrl-H).

    -q <query>, --initial-query <query>
        Use <query> as an initial value for the query box.

    --json-input
        Takes a JSON array with objects with a value property as the entries.

    --json-output
        Return the selection as a JSON array.

    -l <limit>, --limit <limit>
        [default: 50]

        Show up to <limit> items.

    --qwindowgeometry <geometry>
    --qwindowtitle <title>
        Qt options.

    -p <prompt>, --prompt <prompt>
        The prompt string before the ▸ character.

    --source <command>
        Use <command> as input entries.

        This is an alternative to reading entries from STDIN (the default).
        Note that <command> is a shell command (more specifically, `/bin/sh`).
        The command used must not return empty entries.

    --word-delimiters <delimiters>
        Delimiters used for words in addition to those specified
        with --big-word-delimiters. See also Key Bindings section.

        Capital letters and whitespace are always considered word delimiters.

    -h, --help
        Show this.

Key bindings:

    Enter
        Accept the selected item, that is, print it to STDOUT and exit.

    Ctrl+Enter
        Accept the query, that is, print it to STDOUT and exit.

    Esc/Ctrl+D/Ctrl+Space
        Quit without printing anything.

    Tab
        Complete.

    Ctrl+J
        Select next entry.

    Ctrl+K
        Select previous entry.

    Ctrl+N
        Get next history entry and use it as the query.

    Ctrl+P
        Get previous history entry and use it as the query.

    Ctrl+R/F5
        Refresh entries and refilter (only useful if --source is used).

    Ctrl+H
        Set query box to the home query, if specified.

    Ctrl+M
        Copy selected entry to the query box.

    Ctrl+W
        Erase previous word in query box according to word delimiters given.

    Ctrl+Backspace
        Erase previous "big" word in query box according to big word
        delimiters given.

    Ctrl+U
        Erase the query box.

    Ctrl+Z/Ctrl+Y
        Undo/redo operations like erase word or erase the whole query box.

    Alt+P
        Switch between fuzzy and regexp patterns.
"""

from docopt import docopt
from pickout.app import run
from pickout.webenginegui import View

import sys


def main():
	args = docopt(__doc__)
	logger = streamlogger(sys.stderr if args["--debug"] else None)

	sys.exit(run(
		View,
		logger=logger,
		accept_query=args["--accept-query"],
		big_word_delimiters=args["--big-word-delimiters"],
		completion_sep=args["--completion-sep"],
		history_key=args["--history-key"],
		home_query=args["--home-query"],
		initial_query=args["--initial-query"],
		json_input=args["--json-input"],
		json_output=args["--json-output"],
		limit=args["--limit"],
		prompt=args["--prompt"],
		source=args["--source"],
		word_delimiters=args["--word-delimiters"],
	))


class streamlogger:
	def __init__(self, stream):
		self._stream = stream

	def print(self, message):
		if self._stream is not None:
			self._stream.write(message + "\n")
			self._stream.flush()


if __name__ == "__main__":
	main()
