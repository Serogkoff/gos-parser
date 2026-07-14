import os
import glob

sites_dir = "parsers/sites"
files = glob.glob(f"{sites_dir}/*.py")

for filepath in files:
    if filepath.endswith("__init__.py"):
        continue

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Добавляем импорт если его нет
    if "from utils.filters import is_junk" not in content:
        content = "from utils.filters import is_junk\n" + content

    # Заменяем проверку
    content = content.replace("or t in seen:", "or t in seen or is_junk(t):")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ {filepath}")

print("Готово!")