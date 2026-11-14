# Рушій Pikafish

Ця папка в git порожня: бінарники кожен кладе сам під свою ОС.

Обом треба взяти **один і той самий реліз** (зараз це `Pikafish-2026-09-06`), щоб рушій грав однаково.

1. Відкрийте https://github.com/official-pikafish/Pikafish/releases/latest і завантажте `Pikafish.<дата>.7z`
   (близько 51 МБ, мережа `pikafish.nnue` вже всередині). Архіви «Source code» не потрібні.
2. Розпакуйте `.7z`: на Windows через 7-Zip, на Linux `sudo apt install p7zip-full`, далі `7z x Pikafish.*.7z`.
3. Знайдіть в архіві бінарник під свою ОС і скопіюйте сюди:
   - **Linux:** перейменуйте на `pikafish`, потім `chmod +x engines/pikafish`;
   - **Windows:** перейменуйте на `pikafish.exe`;
   - **обидва:** `pikafish.nnue` з того самого архіву. Мережа від іншої версії не завантажиться,
     і програма покаже помилку «Network evaluation parameters compatible with the engine must be available».
4. Бінарники в нових релізах універсальні: самі визначають можливості процесора, тож окрему збірку
   (avx2 тощо) вибирати не треба.

Потрібно отримати:

```
engines/
├── README.md
├── pikafish        (Linux)   або   pikafish.exe   (Windows)
└── pikafish.nnue
```

Перевірка: `python -m pytest tests/test_engine_game.py -k real -v`, тест `test_real_pikafish` має бути PASSED, а не SKIPPED.

Тримати рушій деінде можна, якщо задати шлях у змінній оточення:

- Linux: `export PIKAFISH_PATH=/шлях/до/pikafish`
- Windows (PowerShell): `$env:PIKAFISH_PATH="C:\шлях\до\pikafish.exe"`
