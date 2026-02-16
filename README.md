# Pickout

A heavy dmenu replacement with a fuzzy-matching filtering engine.

## Installation

```bash
pip install pickout
```

### From Source

To build from source, you need Crystal installed:

```bash
git clone https://github.com/rcabralc/pickout.git
cd pickout
pip install .
```

The Crystal filtering engine will be compiled automatically during installation.

## Usage

```bash
ls -1 | pickout --prompt "Select: "
```

## Development

To set up a development environment:

```bash
# Install Crystal (required for building the filter binary)
# See https://crystal-lang.org/install/

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e .
```
