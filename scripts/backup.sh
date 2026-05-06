#!/bin/bash

# AI News Monitor - Database Backup Script
# Creates timestamped backup of news.db with automatic cleanup

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Create backups directory
mkdir -p backups

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backups/news_backup_${TIMESTAMP}.db"

# Check if database exists
if [ ! -f data/news.db ]; then
    echo -e "${YELLOW}Warning: Database file data/news.db not found${NC}"
    exit 1
fi

# Create backup
echo -e "${YELLOW}Creating backup...${NC}"
cp data/news.db "$BACKUP_FILE"

# Compress backup
echo -e "${YELLOW}Compressing backup...${NC}"
gzip "$BACKUP_FILE"
BACKUP_FILE="${BACKUP_FILE}.gz"

# Get file size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)

echo -e "${GREEN}✓ Backup created: $BACKUP_FILE ($BACKUP_SIZE)${NC}"

# Clean up old backups (keep last 7 days)
echo -e "${YELLOW}Cleaning up old backups (keeping last 7 days)...${NC}"
find backups/ -name "news_backup_*.db.gz" -type f -mtime +7 -delete

# Count remaining backups
BACKUP_COUNT=$(find backups/ -name "news_backup_*.db.gz" -type f | wc -l)
echo -e "${GREEN}✓ Total backups: $BACKUP_COUNT${NC}"

echo ""
echo "Backup complete!"
