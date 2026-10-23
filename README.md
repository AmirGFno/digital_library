# Digital Library

یک برنامه دسکتوب برای مدیریت کتابخانه دیجیتال کتاب‌ها، ساخته شده با Python و PyQt6.

## ویژگی‌ها

- 📚 مدیریت کتاب‌های PDF، عکس و آرشیو (CBZ, CBR, 7z, ZIP, TAR)
- 🖼 استخراج خودکار کاور از فایل‌ها (اولین صفحه PDF، اولین عکس آرشیو و غیره)
- 📂 دسته‌بندی کتاب در سری‌ها و مرتب‌سازی بر اساس جلد (volume)
- ✅ علامت‌گذاری کتاب‌های خوانده/نشده
- 🎨 کاور سفارشی برای هر کتاب
- 🔍 جستجو در کتاب‌ها
- 📥 وارد کردن گروهی از یک پوشه (Bulk Import)
- 🌙 تم تیره (Dark Theme)
- 🖥 انتخاب برنامه خواننده سفارشی یا استفاده از برنامه پیش‌فرض سیستم

## نصب و اجرا

### پیش‌نیازها

- Python 3.7+
- وابستگی‌ها در `requirements.txt`:
  - PyQt6
  - Pillow
  - PyMuPDF
  - rarfile
  - py7zr

### نصب

```bash
git clone https://github.com/AmirGFno/digital_library.git
cd digital_library
pip install -r requirements.txt
```

### اجرا

**ویندوز:**
```cmd
run.bat
```

**لینوکس / مک:**
```bash
python main.py
```

## ساختار پروژه

```
digital_library/
├── main.py              # نقطه ورود برنامه
├── config.py            # تنظیمات و ثابت‌ها
├── database.py          # مدیریت دیتابیس SQLite
├── cover_extractor.py   # استخراج کاور از فایل‌ها
├── fix_volume_sorting.py# ابزار Repair ترتیب جلد‌ها
├── requirements.txt     # وابستگی‌های Python
├── run.bat              # اسکریپت اجرا در ویندوز
├── README.md            # این فایل
├── .gitignore           # فایل‌های نادیده گرفته‌شده توسط گیت
├── data/                # دیتابیس و تنظیمات کاربر (نادیده گرفته می‌شود)
├── logs/                # لاگ‌های برنامه (نادیده گرفته می‌شود)
├── thumbnails/          # کاورهای کش‌شده (نادیده گرفته می‌شود)
├── assets/              # فایل‌های استاتیک (کاور پیش‌فرض)
└── ui/                  # رابط کاربری
    ├── __init__.py
    ├── main_window.py   # پنل اصلی
    ├── book_card.py     # کارت نمایش کتاب
    ├── series_panel.py  # پنل سری‌ها (sidebar)
    └── dialogs.py       # دایالگ‌ها
└── utils/               # ابزارها
    ├── __init__.py
    ├── logger.py        # لاگر
    ├── helpers.py       # توابع کمکی
    └── settings.py      # تنظیمات کاربر
```

## مشارکت

بازخوردها و پیشنهادات شما خوش می‌آمد. می‌توانیدIssue باز کنید یا Pull Request بفرستید.

## لایسنس

इस проект injuries؟ (لایسنس هنوز تعریف نشده است)
