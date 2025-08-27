# CineCLI - Terminal Media Browser

CineCLI is a terminal-based media browser that integrates with TMDB, VidSrc, and Torrentio for streaming and downloading media content.

## Features
- 🔍 Search TMDB for movies/TV shows
- 🖼️ Image previews with chafa
- ▶️ Playback via VidSrc or Torrentio
- 💾 Download media with yt-dlp/webtorrent-cli
- 📚 History tracking
- 🎛️ Interactive fzf-based interface

## Installation

### Prerequisites
- Python 3.10+
- External tools:
  ```bash
  # Debian/Ubuntu
  sudo apt-get install fzf mpv chafa
  
  # webtorrent-cli
  npm i -g webtorrent-cli
  
  # yt-dlp (inside virtualenv)
  pip install yt-dlp
  ```

### Install CineCLI
#### Using pipx (recommended)
```bash
# From the project root
pipx install .

# Or include downloader extra (installs yt-dlp)
pipx install ".[download]"

# Verify
cine -h
```

Install directly from GitHub :
```bash
pipx install git+https://github.com/NerdBaba/cinecli.git
pipx install "git+https://github.com/NerdBaba/cinecli.git#egg=cinecli[download]"
```
#### Using uv (fast installer)
```bash
# Install as a standalone tool (adds `cine` to your PATH)
uv tool install .

# Or with extras
uv tool install ".[download]"

# Verify
cine -h
```

Install directly from GitHub:
```bash
uv tool install git+https://github.com/NerdBaba/cinecli.git
uv tool install "git+https://github.com/NerdBaba/cinecli.git#egg=cinecli[download]"
```

#### From source in a virtualenv
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with download extras (yt-dlp)
pip install ".[download]"
```

### Building a Single-Command CLI
After installation, you'll get two commands:
- `cine` 
- `cinecli`

Both provide the same functionality:
```bash
# Verify installation
cine -h

# Example search
cine search "Inception"
```

### Update / Upgrade

#### pipx

- From local path install: reinstall from the repo directory
```bash
# run inside the repo directory
pipx reinstall --force .
# or
pipx uninstall cinecli && pipx install .
```

#### uv

- From local path install: reinstall from the repo directory
```bash
# run inside the repo directory
uv tool install --reinstall .
# or
uv tool uninstall cine && uv tool install .
```


### Uninstall
```bash
# pipx
pipx uninstall cinecli

# uv
uv tool uninstall cine
```

## Configuration
Run initial setup:
```bash
cine setup
```

You'll be prompted for:
1. TMDB API key (get from [TMDB](https://www.themoviedb.org/settings/api))
2. Preferred player (mpv/vlc)
3. Image preview preference
4. Webtorrent temp directory

## Usage
```bash
# Search for media
cine search "Inception"

# Interactive dashboard
cine dashboard

# View history
cine history

# Play media via VidSrc/Torrentio
cine vidsrc movie 27205
cine torrentio tv 1399 -s 1 -e 1
```


### Interactive Features
After selecting media, you'll see an fzf menu with options:
1. Play with VidSrc
2. Play with Torrentio
3. Download with VidSrc
4. Download with Torrentio
5. Skip

For downloads, you'll be prompted to select an output directory.

## Dependencies
- Python: requests, pydantic
- External: fzf, mpv/vlc, chafa, webtorrent-cli, yt-dlp
