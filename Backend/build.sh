#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Building frontend..."
cd ../Frontend
npm install
npm run build

echo "Copying frontend build into Backend/static..."
rm -rf ../Backend/static
cp -r dist ../Backend/static

echo "Installing Python dependencies..."
cd ../Backend
pip install -r requirements.txt
