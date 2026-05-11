#!/bin/bash
set -e

echo "========================================="
echo "  Job Search Copilot - Setup"
echo "========================================="
echo ""

# Find a compatible Python (3.10–3.13). Playwright dependencies (greenlet)
# do not yet ship wheels for Python 3.14 on macOS as of writing.
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$candidate" &> /dev/null; then
        ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" = "3" ] && [ "$minor" -ge 10 ] && [ "$minor" -le 13 ]; then
            PYTHON_BIN=$(command -v "$candidate")
            echo "Using Python: $PYTHON_BIN ($ver)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Error: No compatible Python (3.10–3.13) found."
    echo "Install Python 3.12 first:"
    echo "  brew install python@3.12"
    exit 1
fi
echo ""

# Create virtual environment
VENV_DIR=".venv"
if [ -d "$VENV_DIR" ]; then
    echo "Virtual environment already exists at $VENV_DIR (reusing)"
    # Check if existing venv uses an incompatible Python version
    if [ -f "$VENV_DIR/bin/python" ]; then
        existing_ver=$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
        existing_major=$(echo "$existing_ver" | cut -d. -f1)
        existing_minor=$(echo "$existing_ver" | cut -d. -f2)
        if [ "$existing_major" != "3" ] || [ "$existing_minor" -gt 13 ] || [ "$existing_minor" -lt 10 ]; then
            echo "Existing venv uses incompatible Python $existing_ver — recreating with $PYTHON_BIN"
            rm -rf "$VENV_DIR"
            "$PYTHON_BIN" -m venv "$VENV_DIR"
        fi
    fi
    if [ "$1" = "--recreate" ]; then
        echo "Recreating venv..."
        rm -rf "$VENV_DIR"
        "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi
else
    echo "Creating virtual environment at $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
echo ""

# Activate venv
source "$VENV_DIR/bin/activate"
echo "Activated virtual environment"
echo "  Python: $(which python)"
echo "  Pip:    $(which pip)"
echo ""

# Upgrade pip
echo "Upgrading pip..."
python -m pip install --upgrade pip --quiet
echo ""

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo ""

# Install Playwright Chromium browser
echo "Installing Playwright Chromium browser..."
playwright install chromium
echo ""

# Create required directories
mkdir -p logs data reports

# Check if profile exists
if [ ! -f "config/profile.yaml" ]; then
    echo "Warning: config/profile.yaml not found. Edit it before running the bot."
fi

echo "========================================="
echo "  Setup complete!"
echo "========================================="
echo ""
echo "IMPORTANT: Activate the virtual environment in every new terminal:"
echo ""
echo "    source .venv/bin/activate"
echo ""
echo "To deactivate later:"
echo ""
echo "    deactivate"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit config/profile.yaml:"
echo "       - personal info, skills, resume text"
echo "       - AI provider and API key (Groq is pre-configured)"
echo "       - search keywords, locations, platforms"
echo ""
echo "  2. Set platform credentials as environment variables:"
echo ""
echo "       export LINKEDIN_EMAIL='you@email.com'"
echo "       export LINKEDIN_PASSWORD='yourpassword'"
echo "       export NAUKRI_EMAIL='you@email.com'"
echo "       export NAUKRI_PASSWORD='yourpassword'"
echo "       export INDEED_EMAIL='you@email.com'"
echo "       export INDEED_PASSWORD='yourpassword'"
echo "       # ... and so on for each platform"
echo ""
echo "  3. Dry run first (no AI scoring, no report):"
echo "       python main.py --dry-run"
echo ""
echo "  4. Run with a small limit to test:"
echo "       python main.py --platforms linkedin --limit 3"
echo ""
echo "  5. Real-time dashboard (separate terminal, optional):"
echo "       python main.py --dashboard"
echo "       # Then open http://localhost:7000"
echo ""
echo "  6. Full run:"
echo "       python main.py"
echo ""
echo "  Reminder: this tool is READ-ONLY. It never submits applications."
echo ""
