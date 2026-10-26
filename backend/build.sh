#!/usr/bin/env bash
# Exit on error
set -o errexit

# 1. Upgrade pip to ensure latest wheel support
pip install --upgrade pip

# 2. Install backend dependencies
pip install -r requirements.txt

# 3. Install RAG dependencies from the sibling folder
pip install -r ../FarmIQ-rag/FarmIQ-RAG/requirements.txt
