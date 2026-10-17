# Chrome Lens API для Python

[English](/README.md) | **Русский**

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

Google Lens из командной строки и из Python: распознать текст на картинке (OCR), перевести его, нарисовать перевод поверх картинки, получить координаты слов. Работает с тем же Protobuf-эндпоинтом, что и оверлей Lens в Chrome.

## 📦 Установка

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 | iex
```

**macOS / Linux**

```bash
brew install bropines/tap/lens-scan
```

**Если Python 3.9+ уже есть**

```bash
pip install "chrome-lens-py[clipboard]"
```

Своего Python не нужно ни для чего, кроме последнего варианта. Дальше:

```bash
lens_scan status     # работает? какая это копия? что запущено?
lens_scan update     # обновить потом — тем же способом, которым установлено
```

Остальные способы — uv без скрипта, Scoop, standalone-сборка вообще без Python, Docker, фиксация версии, контрольные суммы и происхождение сборки: **[docs/install.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/install.md)**.

## 🚀 Как пользоваться

```bash
lens_scan shot.png                               # OCR, язык определяется сам
lens_scan shot.png -t en                         # OCR + перевод на английский
lens_scan shot.png ja -t ru -sx                  # японский на входе, русский в буфере обмена
lens_scan shot.png -t en -to out.png             # перевод, нарисованный поверх картинки
lens_scan page.png ja -t en -to out.png --manga  # страница манги: вертикальный текст, облачка
lens_scan scans/ --format jsonl > out.jsonl      # целая папка, по JSON-объекту на картинку
lens_scan sharex --mode both -t ru               # ShareX: Ctrl+O и Ctrl+Shift+O (Windows)
```

`lens_scan -h` показывает те опции, которыми реально пользуются; `lens_scan help options` — полный справочник.

Результат идёт в stdout, всё остальное в stderr, поэтому `lens_scan img.png > out.txt` сохранит только текст. Коды возврата: `0` — всё получилось, `1` — не получилось, `2` — часть картинок из нескольких провалилась, `64` — ошибка в самой команде.

### Команды

| Команда | |
|---|---|
| `lens_scan status` | версия, способ установки, демон, сервис при входе, ShareX, буфер обмена — на одном экране |
| `lens_scan update` | обновить эту копию тем же способом, которым она установлена (uv, brew, Scoop, pip, установщик) |
| `lens_scan daemon status\|start\|stop\|restart\|logs` | «тёплый» фоновый процесс, с которым скан занимает ~0,4 с вместо ~3 с |
| `lens_scan service install\|uninstall\|status\|logs` | держать этот демон запущенным со входа в систему (это нужно быстрому хоткею ShareX) |
| `lens_scan sharex [--mode both] [-t LANG]` | настроить хоткеи ShareX (Windows) |
| `lens_scan config show` | все настройки, их значения и то, какой слой их задал |
| `lens_scan serve` | запустить HTTP API в этом терминале |

У всего, что что-то сообщает, есть `--json`, а `lens_scan help <команда>` объясняет одну команду.

## 🐍 Из Python

```python
import asyncio
from chrome_lens_py import LensAPI

async def main():
    async with LensAPI() as api:
        result = await api.process_image(
            "image.png", ocr_language="ja", target_translation_language="ru"
        )
        print(result["ocr_text"])
        print(result["translated_text"])

asyncio.run(main())
```

## ✨ Что умеет

- **OCR** из файла, URL, байтов, объекта PIL или массива NumPy. Сплошной текст, блоки (абзацы, облачка), строки или слова с геометрией. Вывод: текст, JSON, JSONL, hOCR или TSV.
- **Перевод** на любой язык, который поддерживает Lens.
- **Перевод поверх картинки**, как в оверлее Lens в Chrome: исходный текст стирается, перевод рисуется тем же цветом, под тем же углом и в том же боксе строки. Работают письмо справа налево и вертикальный японский; для страниц манги есть отдельный режим.
- **«Тёплый» демон.** `lens_scan` передаёт команду уже запущенному фоновому процессу, поэтому картинка обрабатывается примерно за 0,4 с вместо 3 с. Демон стартует сам.
- **Интеграция с ShareX**: одна команда настраивает два хоткея, быстрый и надёжный.
- **Python API** с повторами, backoff, запасными ключами и эндпоинтами и лимитом параллелизма.
- **Запрос по области**: перечитать небольшой участок в исходном разрешении.
- **Прокси** (HTTP, HTTPS, SOCKS) и **сборки для Windows, Linux и macOS**.

## 📚 Документация

Подробные страницы написаны на английском.

| Страница | Что внутри |
|---|---|
| [docs/cli.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/cli.md) | Все опции и команды, форматы вывода, коды возврата, файл конфигурации, переменные `LENS_*` и их приоритет. |
| [docs/api.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/api.md) | `LensAPI`: конструктор, `process_image`, `process_region`, поля результата, исключения, примеры. |
| [docs/rendering.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/rendering.md) | Рисование перевода на картинке: вертикальный текст, режимы стирания, обводка, режим манги, шрифты. |
| [docs/daemon.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/daemon.md) | Быстрый режим и «тёплый» демон, сервис при входе в систему, HTTP API, модель безопасности. |
| [docs/install.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/install.md) | Все способы установки, обновление, контрольные суммы и происхождение сборки, фиксация версии, Docker. |
| [docs/sharex.md](https://github.com/bropines/chrome-lens-py/blob/main/docs/sharex.md) | Настройка ShareX: два хоткея, режим аплоадера, ручная настройка, решение проблем. |
| [CHANGELOG.md](CHANGELOG.md) | Что менялось в каждом релизе. |

## ❤️ Поддержка и благодарности

-   **OWOCR**: В большей степени вдохновлен и основан на [OWOCR](https://github.com/AuroraWright/owocr). Благодарю ребят, за их ресерч protobuf и реализацию OCR.
-   **Chrome Lens OCR**: За изначальную реализацию и идеи, которые легли в основу этой библиотеки. Обновление с поддержкой SHAREX изначально было протестировано и добавлено мной в [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr), спасибо за изначальную реализацию и идеи.
-   **Совместная работа с ИИ**: Значительная часть кода версии 3.0, включая рефакторинг архитектуры, асинхронную реализацию и интеграцию с Protobuf, была разработана в сотрудничестве с продвинутым ИИ-ассистентом.
-   **GOOGLE**: За удобную и качественную технологию Lens.
-   **Поддержать автора**: Если эта библиотека оказалась вам полезной, вы можете поддержать автора - **[Boosty](https://boosty.to/pinus)**

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bropines/chrome-lens-py&type=Date)](https://www.star-history.com/#bropines/chrome-lens-py&Date)

### Отказ от ответственности

Этот проект предназначен исключительно для образовательных и экспериментальных целей. Использование сервисов Google должно соответствовать их Условиям предоставления услуг. Автор проекта не несет ответственности за любое неправомерное использование этого программного обеспечения.
