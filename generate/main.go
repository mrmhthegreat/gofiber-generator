package main

import (
	"compress/gzip"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/kluctl/go-embed-python/pip"
)

func main() {
	// This will download wheels for all major platforms (linux, windows, darwin)
	// and save them into the ./data/ directory for embedding.
	err := pip.CreateEmbeddedPipPackagesForKnownPlatforms("generate/requirements.txt", "generate/data/")
	if err != nil {
		panic(err)
	}

	// Manually copy scripts and web_assets into EACH platform folder in data/
	// because pip won't pick them up automatically since we use the PyPI package.
	platforms := []string{"linux-amd64", "linux-arm64", "darwin-amd64", "darwin-arm64", "windows-amd64"}
	for _, p := range platforms {
		dstDir := filepath.Join("generate/data", p)
		
		// Copy web_assets
		fmt.Printf("📦 Copying web_assets to %s...\n", filepath.Join(dstDir, "web_assets"))
		err = copyDir("../generators/web_assets", filepath.Join(dstDir, "web_assets"))
		if err != nil {
			fmt.Printf("⚠️ Warning: failed to copy assets to %s: %v\n", p, err)
		}

		// Copy scripts
		scripts := []string{"launcher.py", "server.py"}
		for _, s := range scripts {
			fmt.Printf("📜 Copying %s to %s...\n", s, dstDir)
			err = copyFile(filepath.Join("..", s), filepath.Join(dstDir, s))
			if err != nil {
				fmt.Printf("⚠️ Warning: failed to copy %s to %s: %v\n", s, p, err)
			}
		}
	}

	// Decompress any .gz files (shared objects) to ensure python can load them
	fmt.Println("\n🔓 Decompressing shared objects...")
	err = decompressGzFiles("generate/data/")
	if err != nil {
		fmt.Printf("⚠️ Warning: decompression failed: %v\n", err)
	}
}

func decompressGzFiles(root string) error {
	return filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && filepath.Ext(path) == ".gz" {
			target := path[:len(path)-3] // remove .gz
			fmt.Printf("  🔓 Ungzipping %s -> %s\n", path, target)
			
			gzFile, err := os.Open(path)
			if err != nil {
				return err
			}
			defer gzFile.Close()

			gzReader, err := gzip.NewReader(gzFile)
			if err != nil {
				return err
			}
			defer gzReader.Close()

			outFile, err := os.Create(target)
			if err != nil {
				return err
			}
			defer outFile.Close()

			_, err = io.Copy(outFile, gzReader)
			if err != nil {
				return err
			}
			
			// Remove the .gz file to save space after it's extracted
			gzFile.Close() // Close before removal
			os.Remove(path)
		}
		return nil
	})
}

func copyDir(src string, dst string) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		targetPath := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(targetPath, 0755)
		}
		return copyFile(path, targetPath)
	})
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}

