# GoFiber Generator — Portable Go Wrapper

This is a Go-based wrapper that embeds the Python generator and its dependencies into a single, standalone binary. It allows running the generator on machines without Python pre-installed.

## 🛠 Prerequisites

- Go 1.22+

## 📦 Quick Installation

You can install the generator directly without cloning the repository:

```bash
go install github.com/mrmhthegreat/gofiber-generator@v0.2.6
```

## 🚀 Build Instructions (Manual)

1.  **Download Dependencies (Wheels)**:
    This command uses `pip` internally to download the correct wheels for Linux, Windows, and macOS.
    ```bash
    go generate ./...
    ```

2.  **Build the Go Binary**:
    ```bash
    go build -o gofiber-gen
    ```

## 📖 Usage (End-User)

Before running the generator for the first time, you **must** initialize the environment:

```bash
./gofiber-gen init
```
This extracts the internal Python environment to `~/.gofiber_generator_env/`.

### CLI Mode
```bash
./gofiber-gen gen --config ./master_config.yaml
```

### Web GUI Mode (Syntax Genesis)
```bash
./gofiber-gen serve
```

## 📦 Distribution

To ship this tool to other users, simply send them the `gofiber-gen` binary. They do **not** need to have Go or Python installed to run it.
