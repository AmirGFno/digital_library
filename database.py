"""
Database module for the Digital Library application.
Uses SQLite with proper connection handling and PRAGMA settings.
"""
import sqlite3
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from config import DATABASE_PATH
from utils.logger import logger


class Database:
    """Database handler with connection pooling and safe operations."""
    
    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            # Set PRAGMA settings
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    def _extract_volume_number(self, volume: Optional[str]) -> Optional[int]:
        """Extract first number from volume string."""
        if not volume:
            return None
        numbers = re.findall(r'\d+', volume)
        return int(numbers[0]) if numbers else None
    
    def _init_database(self):
        """Initialize database schema with backward compatibility."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create series table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # First create basic books table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    series_id INTEGER,
                    volume TEXT,
                    filepath TEXT UNIQUE NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE SET NULL
                )
            """)
            
            # Create metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Get current columns
            cursor.execute("PRAGMA table_info(books)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            
            # Add new columns if they don't exist
            if 'volume_num' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE books ADD COLUMN volume_num INTEGER")
                    logger.info("Added volume_num column")
                    
                    # Update existing books with volume numbers
                    cursor.execute("SELECT id, volume FROM books WHERE volume IS NOT NULL")
                    books = cursor.fetchall()
                    
                    for book_id, volume in books:
                        volume_num = self._extract_volume_number(volume)
                        if volume_num is not None:
                            cursor.execute(
                                "UPDATE books SET volume_num = ? WHERE id = ?",
                                (volume_num, book_id)
                            )
                    
                    logger.info(f"Updated {len(books)} books with volume numbers")
                    
                except Exception as e:
                    logger.warning(f"Could not add volume_num: {e}")
            
            if 'custom_cover' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE books ADD COLUMN custom_cover TEXT")
                    logger.info("Added custom_cover column")
                except Exception as e:
                    logger.warning(f"Could not add custom_cover: {e}")
            
            # Create basic indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_books_series 
                ON books(series_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_books_filepath 
                ON books(filepath)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_books_is_read 
                ON books(is_read)
            """)
            
            # Create volume_num index only if column exists
            cursor.execute("PRAGMA table_info(books)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            
            if 'volume_num' in existing_columns:
                try:
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_books_volume_num 
                        ON books(volume_num)
                    """)
                except Exception as e:
                    logger.warning(f"Could not create volume_num index: {e}")
            
            # Set schema version
            cursor.execute("""
                INSERT OR REPLACE INTO metadata (key, value, updated_at)
                VALUES ('schema_version', '2.0', CURRENT_TIMESTAMP)
            """)
            
            logger.info("Database initialized successfully")
    
    # ==================== SERIES OPERATIONS ====================
    
    def create_series(self, name: str) -> Optional[int]:
        """Create a new series and return its ID."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO series (name) VALUES (?)",
                    (name,)
                )
                series_id = cursor.lastrowid
                logger.info(f"Created series: {name} (ID: {series_id})")
                return series_id
        except sqlite3.IntegrityError:
            logger.warning(f"Series already exists: {name}")
            return None
    
    def get_series(self, series_id: int) -> Optional[Dict]:
        """Get a series by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM series WHERE id = ?",
                (series_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_series(self) -> List[Dict]:
        """Get all series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM series ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    
    def update_series(self, series_id: int, name: str) -> bool:
        """Update a series name."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE series SET name = ? WHERE id = ?",
                    (name, series_id)
                )
                return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            logger.warning(f"Cannot update series: name '{name}' already exists")
            return False
    
    def delete_series(self, series_id: int) -> bool:
        """Delete a series (books will have series_id set to NULL)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM series WHERE id = ?",
                (series_id,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted series ID: {series_id}")
            return deleted
    
    def get_series_by_name(self, name: str) -> Optional[Dict]:
        """Get a series by name."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM series WHERE name = ?",
                (name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_series_unread_count(self, series_id: int) -> int:
        """Get count of unread books in a series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM books WHERE series_id = ? AND is_read = 0",
                (series_id,)
            )
            return cursor.fetchone()[0]
    
    def get_all_series_with_counts(self) -> List[Dict]:
        """Get all series with book counts and unread counts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    s.*,
                    COUNT(b.id) as book_count,
                    SUM(CASE WHEN b.is_read = 0 THEN 1 ELSE 0 END) as unread_count
                FROM series s
                LEFT JOIN books b ON s.id = b.series_id
                GROUP BY s.id
                ORDER BY s.name
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== BOOK OPERATIONS ====================
    
    def add_book(self, filepath: str, title: Optional[str] = None,
                 series_id: Optional[int] = None, volume: Optional[str] = None) -> Optional[int]:
        """Add a new book and return its ID."""
        try:
            # Calculate volume number
            volume_num = self._extract_volume_number(volume)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO books (title, series_id, volume, volume_num, filepath)
                    VALUES (?, ?, ?, ?, ?)
                """, (title, series_id, volume, volume_num, filepath))
                book_id = cursor.lastrowid
                logger.info(f"Added book: {filepath} (ID: {book_id})")
                return book_id
        except sqlite3.IntegrityError:
            logger.warning(f"Book already exists: {filepath}")
            return None
    
    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get a book by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.id = ?
            """, (book_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_book_by_filepath(self, filepath: str) -> Optional[Dict]:
        """Get a book by filepath."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.filepath = ?
            """, (filepath,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_books(self, series_id: Optional[int] = None) -> List[Dict]:
        """Get all books, optionally filtered by series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if series_id is not None:
                cursor.execute("""
                    SELECT b.*, s.name as series_name
                    FROM books b
                    LEFT JOIN series s ON b.series_id = s.id
                    WHERE b.series_id = ?
                """, (series_id,))
            else:
                cursor.execute("""
                    SELECT b.*, s.name as series_name
                    FROM books b
                    LEFT JOIN series s ON b.series_id = s.id
                """)
            
            books = [dict(row) for row in cursor.fetchall()]
            
            # Safe sorting function
            def safe_sort_key(book):
                # Handle all values safely
                series = book.get('series_name') or ''
                if series is None:
                    series = ''
                
                volume_num = book.get('volume_num')
                if volume_num is None:
                    volume_num = 999999
                
                volume = book.get('volume') or ''
                if volume is None:
                    volume = ''
                
                title = book.get('title') or book.get('filepath') or ''
                if title is None:
                    title = ''
                
                return (series, volume_num, volume, title.lower())
            
            books.sort(key=safe_sort_key)
            return books
    
    def get_books_without_series(self) -> List[Dict]:
        """Get all books that don't belong to any series."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, NULL as series_name
                FROM books b
                WHERE b.series_id IS NULL
            """)
            
            books = [dict(row) for row in cursor.fetchall()]
            
            # Safe sorting function
            def safe_sort_key(book):
                volume_num = book.get('volume_num')
                if volume_num is None:
                    volume_num = 999999
                
                volume = book.get('volume') or ''
                if volume is None:
                    volume = ''
                
                title = book.get('title') or book.get('filepath') or ''
                if title is None:
                    title = ''
                
                return (volume_num, volume, title.lower())
            
            books.sort(key=safe_sort_key)
            return books
    
    def update_book(self, book_id: int, **kwargs) -> bool:
        """Update book fields. Accepts: title, series_id, volume, is_read, custom_cover."""
        allowed_fields = {'title', 'series_id', 'volume', 'is_read', 'custom_cover'}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return False
        
        # If volume is updated, recalculate volume_num
        if 'volume' in updates:
            volume = updates['volume']
            updates['volume_num'] = self._extract_volume_number(volume)
        
        updates['updated_at'] = datetime.now().isoformat()
        
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [book_id]
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE books SET {set_clause} WHERE id = ?",
                values
            )
            return cursor.rowcount > 0
    
    def toggle_book_read(self, book_id: int) -> Optional[bool]:
        """Toggle the read status of a book. Returns new status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT is_read FROM books WHERE id = ?",
                (book_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            new_status = 0 if row['is_read'] else 1
            cursor.execute("""
                UPDATE books 
                SET is_read = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_status, book_id))
            
            logger.info(f"Book {book_id} marked as {'read' if new_status else 'unread'}")
            return bool(new_status)
    
    def delete_book(self, book_id: int) -> bool:
        """Delete a book from the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM books WHERE id = ?",
                (book_id,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted book ID: {book_id}")
            return deleted
    
    # Custom cover operations
    def set_custom_cover(self, book_id: int, cover_path: str) -> bool:
        """Set a custom cover image for a book."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE books SET custom_cover = ? WHERE id = ?",
                (cover_path, book_id)
            )
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Set custom cover for book {book_id}: {cover_path}")
            return updated
    
    def get_custom_cover(self, book_id: int) -> Optional[str]:
        """Get custom cover path for a book."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT custom_cover FROM books WHERE id = ?",
                (book_id,)
            )
            row = cursor.fetchone()
            return row['custom_cover'] if row and row['custom_cover'] else None
    
    def remove_custom_cover(self, book_id: int) -> bool:
        """Remove custom cover from a book."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE books SET custom_cover = NULL WHERE id = ?",
                (book_id,)
            )
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Removed custom cover from book {book_id}")
            return updated
    
    # Other operations
    def get_recent_books(self, limit: int = 20) -> List[Dict]:
        """Get recently added books."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                ORDER BY b.created_at DESC
                LIMIT ?
            """, (limit,))
            
            books = [dict(row) for row in cursor.fetchall()]
            
            # Safe sorting
            def safe_sort_key(book):
                series = book.get('series_name') or ''
                if series is None:
                    series = ''
                
                volume_num = book.get('volume_num')
                if volume_num is None:
                    volume_num = 999999
                
                volume = book.get('volume') or ''
                if volume is None:
                    volume = ''
                
                title = book.get('title') or book.get('filepath') or ''
                if title is None:
                    title = ''
                
                return (series, volume_num, volume, title.lower())
            
            books.sort(key=safe_sort_key)
            return books
    
    def get_unread_books(self) -> List[Dict]:
        """Get all unread books."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.is_read = 0
            """)
            
            books = [dict(row) for row in cursor.fetchall()]
            
            # Safe sorting
            def safe_sort_key(book):
                series = book.get('series_name') or ''
                if series is None:
                    series = ''
                
                volume_num = book.get('volume_num')
                if volume_num is None:
                    volume_num = 999999
                
                volume = book.get('volume') or ''
                if volume is None:
                    volume = ''
                
                title = book.get('title') or book.get('filepath') or ''
                if title is None:
                    title = ''
                
                return (series, volume_num, volume, title.lower())
            
            books.sort(key=safe_sort_key)
            return books
    
    def get_total_unread_count(self) -> int:
        """Get total count of unread books."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM books WHERE is_read = 0")
            return cursor.fetchone()[0]
    
    def get_total_book_count(self) -> int:
        """Get total count of books."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM books")
            return cursor.fetchone()[0]
    
    def search_books(self, query: str) -> List[Dict]:
        """Search books by title or filepath."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            search_term = f"%{query}%"
            cursor.execute("""
                SELECT b.*, s.name as series_name
                FROM books b
                LEFT JOIN series s ON b.series_id = s.id
                WHERE b.title LIKE ? OR b.filepath LIKE ?
            """, (search_term, search_term))
            
            books = [dict(row) for row in cursor.fetchall()]
            
            # Safe sorting
            def safe_sort_key(book):
                series = book.get('series_name') or ''
                if series is None:
                    series = ''
                
                volume_num = book.get('volume_num')
                if volume_num is None:
                    volume_num = 999999
                
                volume = book.get('volume') or ''
                if volume is None:
                    volume = ''
                
                title = book.get('title') or book.get('filepath') or ''
                if title is None:
                    title = ''
                
                return (series, volume_num, volume, title.lower())
            
            books.sort(key=safe_sort_key)
            return books
    
    def bulk_add_books(self, books: List[Dict]) -> Tuple[int, int]:
        """
        Bulk add books. Each dict should have 'filepath' and optionally
        'title', 'series_id', 'volume'.
        Returns (success_count, skip_count).
        """
        success = 0
        skipped = 0
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for book in books:
                try:
                    volume_num = self._extract_volume_number(book.get('volume'))
                    cursor.execute("""
                        INSERT INTO books (title, series_id, volume, volume_num, filepath)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        book.get('title'),
                        book.get('series_id'),
                        book.get('volume'),
                        volume_num,
                        book['filepath']
                    ))
                    success += 1
                except sqlite3.IntegrityError:
                    skipped += 1
        
        logger.info(f"Bulk import: {success} added, {skipped} skipped")
        return success, skipped
    
    def book_exists(self, filepath: str) -> bool:
        """Check if a book with the given filepath exists."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM books WHERE filepath = ?",
                (filepath,)
            )
            return cursor.fetchone() is not None
    
    def update_all_volume_numbers(self) -> int:
        """
        Update volume_num for all books based on their volume field.
        Returns number of books updated.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all books with volume
            cursor.execute("SELECT id, volume FROM books WHERE volume IS NOT NULL")
            books = cursor.fetchall()
            
            updated_count = 0
            
            for book_id, volume in books:
                volume_num = self._extract_volume_number(volume)
                if volume_num is not None:
                    cursor.execute(
                        "UPDATE books SET volume_num = ? WHERE id = ?",
                        (volume_num, book_id)
                    )
                    updated_count += 1
            
            logger.info(f"Updated volume numbers for {updated_count} books")
            return updated_count


# Global database instance
db = Database()