# Microsoft Learn Course Downloader

This tool downloads course materials and metadata from Microsoft Learn using the Catalog API.

## Installation

```bash
pip install requests
```

## Usage

### Download a specific course by code:
```bash
python3 microsoft_learn_downloader.py AI-102T00
```

### Download from a learning path URL:
```bash
python3 microsoft_learn_downloader.py "https://learn.microsoft.com/en-us/training/courses/ai-102t00"
```

### Specify output directory:
```bash
python3 microsoft_learn_downloader.py AI-102T00 --output my_courses
```

## What it downloads:

1. **Course metadata** - JSON file with course information
2. **Course overview page** - HTML of the main course page
3. **Module metadata** - JSON files for each module
4. **Module overview pages** - HTML of each module page
5. **Unit pages** - HTML of individual units within modules

## Output Structure:

```
downloads/
└── AI-102T00/
    ├── course_metadata.json
    ├── course_overview.html
    └── modules/
        ├── module-uid-1/
        │   ├── module_metadata.json
        │   ├── module_overview.html
        │   └── units/
        │       ├── unit-1.html
        │       └── unit-2.html
        └── module-uid-2/
            └── ...
```

## Examples:

### Popular Courses:
- `AI-102T00` - Develop AI solutions in Azure
- `AZ-900T00` - Azure Fundamentals
- `DP-203T00` - Data Engineering on Microsoft Azure

### Finding Course Codes:
You can find course codes by:
1. Visiting the course page on Microsoft Learn
2. Looking at the URL - the code is usually at the end
3. Using the test script to search for courses

## Limitations:

- Downloads HTML pages and metadata only
- Does not download videos, interactive content, or assessments
- Rate limited to avoid overwhelming Microsoft's servers
- Some content may require authentication to access

## Troubleshooting:

If a course is not found, try:
1. Checking the exact course code
2. Using the full URL instead of just the code
3. Running the test script to see available courses