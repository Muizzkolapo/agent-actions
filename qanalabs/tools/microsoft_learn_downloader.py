#!/usr/bin/env python3
"""
Microsoft Learn Course Downloader
Downloads course materials and metadata from Microsoft Learn using the Catalog API
"""

import requests
import json
import os
import time
from urllib.parse import urlparse, urljoin
from pathlib import Path
import argparse
import sys
from typing import Dict, List, Optional

class MicrosoftLearnDownloader:
    def __init__(self, base_dir: str = "downloads"):
        self.base_url = "https://learn.microsoft.com"
        self.api_url = "https://learn.microsoft.com/api/catalog/"
        self.base_dir = Path(base_dir)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_catalog_data(self, **params) -> Dict:
        """Fetch data from Microsoft Learn Catalog API"""
        try:
            response = self.session.get(self.api_url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching catalog data: {e}")
            return {}
    
    def find_course_by_code(self, course_code: str) -> Optional[Dict]:
        """Find a specific course by its code (e.g., AI-102T00)"""
        print(f"Searching for course: {course_code}")
        
        # Search in courses - handle both formats: AI-102T00 and course.ai-102t00
        data = self.fetch_catalog_data(type="courses")
        courses = data.get("courses", [])
        
        for course in courses:
            uid = course.get("uid", "")
            # Check exact match and partial match
            if (uid.upper() == course_code.upper() or 
                uid.upper() == f"course.{course_code.lower()}" or
                course_code.upper() in uid.upper()):
                return course
        
        # Also search in learning paths if not found in courses
        data = self.fetch_catalog_data(type="learningPaths")
        learning_paths = data.get("learningPaths", [])
        
        for path in learning_paths:
            uid = path.get("uid", "")
            if (course_code.upper() in uid.upper() or
                course_code.upper() in path.get("title", "").upper()):
                return path
        
        return None
    
    def get_course_modules(self, course_data: Dict) -> List[Dict]:
        """Get modules associated with a course or learning path"""
        modules = []
        
        # Check if it's a learning path with modules
        if "modules" in course_data and isinstance(course_data["modules"], list):
            module_uids = []
            for module in course_data["modules"]:
                if isinstance(module, dict):
                    module_uids.append(module.get("uid"))
                elif isinstance(module, str):
                    module_uids.append(module)
            
            # Fetch detailed module information
            data = self.fetch_catalog_data(type="modules")
            all_modules = data.get("modules", [])
            
            for module in all_modules:
                if module.get("uid") in module_uids:
                    modules.append(module)
        
        # If no modules found, try to get related modules by product/subject
        if not modules and "products" in course_data:
            products = course_data.get("products", [])
            if products:
                # Get modules for the same products
                data = self.fetch_catalog_data(type="modules")
                all_modules = data.get("modules", [])
                
                for module in all_modules:
                    module_products = module.get("products", [])
                    if any(prod in products for prod in module_products):
                        modules.append(module)
                
                # Limit to reasonable number
                modules = modules[:20]
        
        return modules
    
    def download_content_page(self, url: str, file_path: Path) -> bool:
        """Download HTML content from a URL"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Create directory if it doesn't exist
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
            
            print(f"Downloaded: {file_path}")
            return True
            
        except requests.RequestException as e:
            print(f"Error downloading {url}: {e}")
            return False
    
    def save_metadata(self, data: Dict, file_path: Path) -> None:
        """Save metadata as JSON"""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"Saved metadata: {file_path}")
    
    def download_course(self, course_code: str) -> bool:
        """Download a complete course by code"""
        print(f"\n=== Downloading Course: {course_code} ===")
        
        # Find the course
        course_data = self.find_course_by_code(course_code)
        if not course_data:
            print(f"Course {course_code} not found!")
            return False
        
        # Create course directory
        course_dir = self.base_dir / course_code
        course_dir.mkdir(parents=True, exist_ok=True)
        
        # Save course metadata
        self.save_metadata(course_data, course_dir / "course_metadata.json")
        
        # Download main course page
        course_url = urljoin(self.base_url, course_data.get("url", ""))
        if course_url:
            self.download_content_page(course_url, course_dir / "course_overview.html")
        
        # Get and download modules
        modules = self.get_course_modules(course_data)
        print(f"Found {len(modules)} modules")
        
        for i, module in enumerate(modules, 1):
            module_uid = module.get("uid", f"module_{i}")
            module_dir = course_dir / "modules" / module_uid
            
            print(f"\nDownloading Module {i}: {module.get('title', 'Unknown')}")
            
            # Save module metadata
            self.save_metadata(module, module_dir / "module_metadata.json")
            
            # Download module page
            module_url = urljoin(self.base_url, module.get("url", ""))
            if module_url:
                self.download_content_page(module_url, module_dir / "module_overview.html")
            
            # Download units if available
            units = module.get("units", [])
            for j, unit in enumerate(units, 1):
                if isinstance(unit, dict):
                    unit_uid = unit.get("uid", f"unit_{j}")
                    unit_title = unit.get("title", "Unknown")
                    unit_url = urljoin(self.base_url, unit.get("url", ""))
                elif isinstance(unit, str):
                    unit_uid = unit
                    unit_title = unit
                    unit_url = ""
                else:
                    continue
                
                unit_file = module_dir / "units" / f"{unit_uid}.html"
                
                if unit_url:
                    print(f"  Downloading Unit {j}: {unit_title}")
                    self.download_content_page(unit_url, unit_file)
            
            # Rate limiting
            time.sleep(1)
        
        print(f"\n✓ Course {course_code} download completed!")
        print(f"Files saved to: {course_dir}")
        return True
    
    def download_learning_path(self, path_url: str) -> bool:
        """Download an entire learning path from a URL"""
        print(f"\n=== Downloading Learning Path: {path_url} ===")
        
        # Extract path ID from URL
        parsed_url = urlparse(path_url)
        path_parts = parsed_url.path.strip('/').split('/')
        
        # Find learning path in catalog
        data = self.fetch_catalog_data(type="learningPaths")
        learning_paths = data.get("learningPaths", [])
        
        matching_path = None
        for path in learning_paths:
            path_url_parts = path.get("url", "").strip('/').split('/')
            if any(part in path_parts for part in path_url_parts):
                matching_path = path
                break
        
        if not matching_path:
            print("Learning path not found in catalog!")
            return False
        
        # Download the learning path as a course
        path_uid = matching_path.get("uid", "learning_path")
        return self.download_course(path_uid)

def main():
    parser = argparse.ArgumentParser(description="Download Microsoft Learn courses and learning paths")
    parser.add_argument("target", help="Course code (e.g., AI-102T00) or learning path URL")
    parser.add_argument("--output", "-o", default="downloads", help="Output directory")
    parser.add_argument("--type", choices=["course", "path", "auto"], default="auto", 
                       help="Type of content to download")
    
    args = parser.parse_args()
    
    downloader = MicrosoftLearnDownloader(args.output)
    
    if args.type == "course" or (args.type == "auto" and not args.target.startswith("http")):
        success = downloader.download_course(args.target)
    elif args.type == "path" or (args.type == "auto" and args.target.startswith("http")):
        success = downloader.download_learning_path(args.target)
    else:
        print("Invalid target. Provide either a course code or learning path URL.")
        return 1
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())