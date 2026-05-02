#!/bin/bash
set -e

# Create dist directory
mkdir -p dist

echo "🚀 Starting Multi-Platform Build..."

# 1. Ensure assets are bundled
echo "🔄 Bundling Python runtime and assets..."
go generate ./...

# 2. Build binaries
echo "🐧 Building for Linux (64-bit)..."
GOOS=linux GOARCH=amd64 go build -o dist/gofiber-gen-linux-amd64

echo "🐧 Building for Linux (ARM64)..."
GOOS=linux GOARCH=arm64 go build -o dist/gofiber-gen-linux-arm64

echo "🪟 Building for Windows (64-bit)..."
GOOS=windows GOARCH=amd64 go build -o dist/gofiber-gen-windows-amd64.exe

echo "🍎 Building for MacOS (Intel)..."
GOOS=darwin GOARCH=amd64 go build -o dist/gofiber-gen-darwin-amd64

echo "🍎 Building for MacOS (Apple Silicon/M1/M2)..."
GOOS=darwin GOARCH=arm64 go build -o dist/gofiber-gen-darwin-arm64

echo ""
echo "✅ Done! All binaries are ready in the 'wrapper/dist/' folder:"
ls -F dist/
