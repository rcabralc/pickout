#!/usr/bin/python
"""Pickout.

Usage:
    pickout [--accept-input]
            [--big-word-delimiters=<delimiters>]
            [--completion-sep=<sep>]
            [--debug]
            [--history-key=<key>]
            [--home=<input>]
            [--input=<input>]
            [--json-output]
            [--limit=<limit>]
            [--no-center]
            [--source=<command>]
            [--title=<title>]
            [--word-delimiters=<delimiters>]

Options:
    --accept-input
        Allow any text typed in the search input to be accepted through
        Ctrl-Enter.

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
        directory, it'll remember the previous input, allowing the user to
        reuse it.

    --home <input>
        Defines an input to be the "home" input (set by pressing Ctrl-H).

    -i <input>, --input <input>
        Use <input> as a initial value.

    --json-output
        Return the selection as a JSON array.

    -l <limit>, --limit <limit>
        [default: 50]

        Show up to <limit> items.

    --no-center
        Do not move the menu window to the center of the screen.

        By default, the menu is centered in the screen.  Disabling centering
        will cause the menu to not be positioned at the center of the screen
        and, as such, window managers may decide to place the window as it fits.

    --source <command>
        Use <command> as input entries.

        This is an alternative to reading entries from STDIN (the default).
        Note that <command> is a shell command (more specifically, `/bin/sh`).
        The command used must not return empty entries.

    --title <title>
        Set the window title to <title>.

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
        Accept the input, that is, print it to STDOUT and exit.

    Esc/Ctrl+D/Ctrl+Space
        Quit without printing anything.

    Tab
        Complete.

    CTRL+J
        Select next entry.

    CTRL+K
        Select previous entry.

    Ctrl+N
        Get next history entry and use it as the input.

    Ctrl+P
        Get previous history entry and use it as the input.

    Ctrl+R/F5
        Refresh entries and refilter (only useful if --source is used).

    Ctrl+H
        Set input to the home, if specified.

    Ctrl+M
        Copy selected entry to the input box.

    Ctrl+W
        Erase previous word in input box according to word delimiters given.

    Ctrl+Backspace
        Erase previous "big" word in input box according to big word
        delimiters given.

    Ctrl+U
        Erase the input box.

    Ctrl+Z/Ctrl-Y
        Undo/redo operations like erase word or erase the whole input.
"""

from app import run
from docopt import docopt

import json
import sys


def main(args):
	logger = streamlogger(sys.stderr if args['--debug'] else None)

	return run(
		logger=logger,
		accept_input=args['--accept-input'],
		big_word_delimiters=args['--big-word-delimiters'],
		center=not args['--no-center'],
		completion_sep=args['--completion-sep'],
		history_key=args['--history-key'],
		home=args['--home'],
		input=args['--input'],
		json_output=args['--json-output'],
		limit=args['--limit'],
		source=args['--source'],
		title=args['--title'],
		word_delimiters=args['--word-delimiters']
	)


class streamlogger:
	def __init__(self, stream):
		self._stream = stream

	def print(self, message):
		if self._stream is not None:
			self._stream.write(message + '\n')
			self._stream.flush()


if __name__ == '__main__':
	sys.exit(main(docopt(__doc__)))
