#!/usr/bin/env python3
"""
Fix volume sorting issues in existing database.
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import db

def main():
    print("=" * 50)
    print("Fixing Volume Sorting Issues")
    print("=" * 50)
    
    # Update all volume numbers
    print("\n1. Updating volume numbers for all books...")
    updated = db.update_all_volume_numbers()
    print(f"   Updated {updated} books")
    
    # Test sorting
    print("\n2. Testing sorting...")
    all_books = db.get_all_books()
    
    # Group by series for display
    series_dict = {}
    for book in all_books:
        series = book.get('series_name', 'No Series')
        if series not in series_dict:
            series_dict[series] = []
        series_dict[series].append(book)
    
    # Display sorted results
    print("\nSorted books by series and volume:")
    print("-" * 40)
    
    for series, books in sorted(series_dict.items()):
        if series == 'No Series':
            print(f"\n📚 {series}:")
        else:
            print(f"\n📚 Series: {series}")
        
        for book in books:
            title = book.get('title', Path(book['filepath']).stem)
            volume = book.get('volume', '')
            volume_num = book.get('volume_num', 'N/A')
            print(f"   Vol.{volume} (num:{volume_num}) - {title[:30]}")
    
    print("\n" + "=" * 50)
    print("Sorting fix completed!")
    print("Books should now sort as: 1, 2, 3, ..., 10, 11, ...")
    print("=" * 50)

if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")