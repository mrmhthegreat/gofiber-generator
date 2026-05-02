package main

import (
	"embed"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"

	"github.com/kluctl/go-embed-python/embed_util"
	"github.com/kluctl/go-embed-python/python"
)

//go:embed all:generate/data
var pythonLib embed.FS

func main() {
	// Initialize embedded python distribution
	ep, err := python.NewEmbeddedPython("gofiber-generator")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error initializing embedded python: %v\n", err)
		os.Exit(1)
	}

	// Persistent directory for the environment
	home, _ := os.UserHomeDir()
	envDir := filepath.Join(home, ".gofiber_generator_env")

	// Check for commands
	if len(os.Args) > 1 && os.Args[1] == "init" {
		initializeEnv(pythonLib, envDir)
		return
	}

	// Verify environment exists
	if _, err := os.Stat(envDir); os.IsNotExist(err) {
		fmt.Println("❌ Error: Environment not initialized.")
		fmt.Println("Please run: gofiber-generator init")
		os.Exit(1)
	}

	// Add the persistent environment to PYTHONPATH
	// Note: We need to detect the platform to point to the right subfolder in envDir
	platform := fmt.Sprintf("%s-%s", runtime.GOOS, runtime.GOARCH)
	ep.AddPythonPath(filepath.Join(envDir, platform))

	// Determine command
	cmdName := "generator"
	remainingArgs := os.Args[1:]

	if len(os.Args) > 1 {
		if os.Args[1] == "init" {
			initializeEnv(pythonLib, envDir)
			return
		} else if os.Args[1] == "serve" {
			cmdName = "server" // Points to server.py
			remainingArgs = os.Args[2:]
		} else if os.Args[1] == "gui" {
			cmdName = "launcher" // Points to launcher.py
			remainingArgs = os.Args[2:]
		} else if os.Args[1] == "gen" {
			cmdName = "generator"
			remainingArgs = os.Args[2:]
		}
	}

	// Prepare command
	args := []string{"-m", cmdName}
	args = append(args, remainingArgs...)

	cmd, err := ep.PythonCmd(args...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error creating python command: %v\n", err)
		os.Exit(1)
	}

	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin

	err = cmd.Run()
	if err != nil {
		os.Exit(1)
	}
}

func initializeEnv(fsys embed.FS, targetDir string) {
	fmt.Println("🚀 Initializing GoFiber Generator environment...")

	// Use fs.Sub to correctly point to the contents of generate/data
	subData, err := fs.Sub(fsys, "generate/data")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error accessing embedded data: %v\n", err)
		os.Exit(1)
	}

	// Extract everything to the persistent directory
	_, err = embed_util.NewEmbeddedFilesWithTmpDir(subData, targetDir, false)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error extracting environment: %v\n", err)
		os.Exit(1)
	}

	// NewEmbeddedFilesWithTmpDir extracts files.
	// We don't call Cleanup because we want it to stay in the home folder.
	fmt.Printf("✅ Environment successfully prepared in %s\n", targetDir)
	fmt.Println("You can now run 'gofiber-generator'")
}
