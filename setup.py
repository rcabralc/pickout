import subprocess
import sys
from pathlib import Path

from setuptools import Command, setup
from setuptools.command.build import build


class FilterBuild(build):
	"""Custom build command that compiles Crystal code for the filtering engine."""

	def run(self):
		self._compile_crystal()
		super().run()

	def _compile_crystal(self):
		src_dir = Path(__file__).parent / 'src' / 'pickout'
		filter_src = src_dir / 'filter.cr'

		print('Compiling Crystal filtering engine...')

		try:
			command = [
				'crystal',
				'build',
				'filter.cr',
				'-o',
				'filter',
				'--release',
				'--no-debug',
				'-Dpreview_mt'
			]
			result = subprocess.run(
				command,
				cwd=src_dir,
				capture_output=True,
				text=True
			)
			if result.returncode != 0:
				print(f'Crystal compilation failed: {result.stderr}', file=sys.stderr)
				sys.exit(1)
			print('Crystal compilation successful')
		except FileNotFoundError:
			print('Error: crystal not found in PATH.', file=sys.stderr)
			sys.exit(1)


setup(cmdclass={'build': FilterBuild})
