"""
ORCUS Downloader - Main Entry Point
(C) Copyright 2026. OrcusExtreme
"""
import os
import sys

# Ensure src directory is in Python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from app import OrcusDownloaderApp

if __name__ == "__main__":
    app = OrcusDownloaderApp()
    app.mainloop()
