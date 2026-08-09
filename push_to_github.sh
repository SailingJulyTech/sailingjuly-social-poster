#!/usr/bin/env bash
#
# One-shot script to push this repo to GitHub under the SailingJulyTech
# account. Run it from anywhere -- it cd's to its own location first.
#
#   chmod +x push_to_github.sh
#   ./push_to_github.sh
#
# Safe to re-run: it skips steps that are already done (existing .git,
# already-authenticated gh, already-created remote repo, no-op commits).
#
# Optional env vars:
#   SAILINGJULY_GIT_EMAIL   skip the email prompt by setting this up front
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

GITHUB_USER="SailingJulyTech"
REPO_NAME="sailingjuly-social-poster"
GIT_NAME="SailingJulyTech"
GIT_EMAIL="${SAILINGJULY_GIT_EMAIL:-}"

echo "== SailingJuly social poster: push to GitHub =="
echo "Working in: $REPO_DIR"
echo

# --- 1. gh CLI present? ------------------------------------------------
if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) not found."
  if command -v brew >/dev/null 2>&1; then
    read -r -p "Install it now with Homebrew? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      brew install gh
    else
      echo "Install gh manually from https://cli.github.com and re-run this script."
      exit 1
    fi
  else
    echo "Homebrew not found either. Install gh manually from https://cli.github.com"
    echo "or install Homebrew first from https://brew.sh"
    exit 1
  fi
fi

# --- 2. Authenticated, and as the right account? ------------------------
CURRENT_USER="$(gh api user --jq .login 2>/dev/null || true)"
if [[ -z "$CURRENT_USER" ]]; then
  echo "Not authenticated with gh yet. Launching 'gh auth login'..."
  gh auth login
  CURRENT_USER="$(gh api user --jq .login)"
fi

if [[ "$CURRENT_USER" != "$GITHUB_USER" ]]; then
  echo "WARNING: gh is authenticated as '$CURRENT_USER', not '$GITHUB_USER'."
  read -r -p "Continue and push under '$CURRENT_USER' instead? [y/N] " ans
  if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    echo "Aborting. Run: gh auth login   (choose the SailingJulyTech account), then re-run this script."
    exit 1
  fi
  GITHUB_USER="$CURRENT_USER"
fi
echo "Authenticated as: $CURRENT_USER"

# --- 3. Resolve the commit email ----------------------------------------
if [[ -z "$GIT_EMAIL" ]]; then
  DEFAULT_EMAIL="$(gh api user --jq '(.id|tostring) + "+" + .login + "@users.noreply.github.com"' 2>/dev/null || true)"
  read -r -p "Git commit email to use [${DEFAULT_EMAIL}]: " input_email
  GIT_EMAIL="${input_email:-$DEFAULT_EMAIL}"
fi
if [[ -z "$GIT_EMAIL" ]]; then
  echo "No email resolved. Re-run with SAILINGJULY_GIT_EMAIL=you@example.com ./push_to_github.sh"
  exit 1
fi
echo "Commit identity: $GIT_NAME <$GIT_EMAIL>"
echo

# --- 4. git init / config / commit --------------------------------------
if [[ ! -d .git ]]; then
  git init
fi
git config user.name "$GIT_NAME"
git config user.email "$GIT_EMAIL"

git add .
if git diff --cached --quiet 2>/dev/null; then
  echo "Nothing new to commit (working tree already matches last commit)."
else
  git commit -m "Initial commit: social auto-poster for Facebook, Instagram, TikTok"
fi

# Only rename to main if this is a fresh repo on some other default branch name
git branch -M main

# --- 5. Create (if needed) and push -------------------------------------
if gh repo view "${GITHUB_USER}/${REPO_NAME}" >/dev/null 2>&1; then
  echo "Repo ${GITHUB_USER}/${REPO_NAME} already exists on GitHub -- pushing to it."
  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
  fi
  git push -u origin main
else
  gh repo create "${GITHUB_USER}/${REPO_NAME}" --private --source=. --remote=origin --push
fi

echo
echo "Done: https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo "Next: add the six API secrets under Settings -> Secrets and variables -> Actions."
