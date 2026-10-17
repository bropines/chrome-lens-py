# Chrome Lens API для Python

[English](/README.md) | **Русский**

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

Асинхронная Python-библиотека и утилита командной строки (`lens_scan`) для Google Lens. Распознаёт текст на картинках (OCR), переводит его и отдаёт координаты слов. Работает с тем же Protobuf-эндпоинтом, что и оверлей Lens в Chrome.

## ✨ Возможности

- **OCR** из файла, URL, байтов, объекта PIL или массива NumPy. Сплошной текст, блоки (абзацы, облачка), строки или слова с геометрией. Вывод: текст, JSON, JSONL, hOCR или TSV.
- **Перевод** на любой язык, который поддерживает Lens.
- **Перевод поверх картинки**, как в оверлее Lens в Chrome: исходный текст стирается, перевод рисуется тем же цветом, под тем же углом и в том же боксе строки. Работают письмо справа налево и вертикальный японский; для страниц манги есть отдельный режим.
- **«Тёплый» демон.** `lens_scan` передаёт команду уже запущенному фоновому процессу, поэтому картинка обрабатывается примерно за 0,4 с вместо 3 с. Демон стартует сам.
- **Интеграция с ShareX**: одна команда настраивает два хоткея, быстрый и надёжный.
- **Python API** с повторами, backoff, запасными ключами и эндпоинтами и лимитом параллелизма.
- **Запрос по области**: перечитать небольшой участок в исходном разрешении.
- **Прокси** (HTTP, HTTPS, SOCKS) и **сборки для Windows, Linux и macOS**.

## 📦 Установка

| Способ | Команда | Примечания |
|---|---|---|
| **Homebrew** (macOS, Linux) | `brew install bropines/tap/lens-scan` | Python не нужен. Apple Silicon и x86_64 Linux. |
| **uv**, Windows | `irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 \| iex` | Python не нужен: uv принесёт свой. Исполняемого файла от нас нет, антивирусу не к чему придраться. |
| **uv**, Linux / macOS | `curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.sh \| sh` | То же самое. |
| **Standalone**, Windows | `irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 \| iex` | Python не нужен. Самый быстрый старт (~0,2 с). Если антивирус отправит скомпилированный `lens_scan.exe` в карантин, установщик сам поставит **portable-сборку**: она запускается через подписанный `python.exe` с python.org. Выбрать вручную: `$env:LENS_SCAN_FLAVOR = 'portable'`. |
| **Standalone**, Linux / macOS | `curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh \| sh` | Python не нужен. Проверяет SHA-256 загрузки. |
| **Scoop** (Windows) | `scoop bucket add lens https://github.com/bropines/chrome-lens-py`, затем `scoop install lens-scan` | Или `lens-scan-portable`. |
| **pip** | `pip install "chrome-lens-py[clipboard]"` | Свой Python 3.9 или новее. Extra включает `--sharex`. |
| **Docker** | `docker run -d -p 127.0.0.1:8765:8765 -e LENS_TOKEN=change-me ghcr.io/bropines/chrome-lens-py` | Запускает HTTP-сервер. `LENS_TOKEN` обязателен. |

Проверить установку: `lens_scan --version` покажет, какая именно копия запускается. Контрольные суммы, аттестации, фиксация версии и остальное: [docs/install.md](docs/install.md).

## 🚀 Быстрый старт

```bash
lens_scan image.png                              # OCR, язык определяется сам
lens_scan image.png -t en                        # OCR + перевод на английский
lens_scan image.png ja -t ru -sx                 # распознать японский, перевести, скопировать в буфер обмена
lens_scan image.png -t en -to out.png            # заодно сохранить картинку с нарисованным переводом
lens_scan page.png ja -t en -to out.png --manga  # страница манги: вертикальный японский, облачка
lens_scan scans/ --format jsonl > out.jsonl      # целая папка, по JSON-объекту на картинку
lens_scan --setup-sharex --mode both -t ru       # ShareX: Ctrl+O и Ctrl+Shift+O (Windows)
```

Из Python (все вызовы `async`):

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

Данные результата идут в stdout, всё остальное в stderr, поэтому `lens_scan img.png > out.txt` сохранит только текст. Код возврата: `0` — все картинки обработаны, `1` — все провалились, `2` — часть провалилась.

## 📚 Документация

Подробные страницы написаны на английском.

| Страница | Что внутри |
|---|---|
| [docs/cli.md](docs/cli.md) | Все опции, форматы вывода, коды возврата, файл конфигурации, переменные `LENS_*` и их приоритет. |
| [docs/api.md](docs/api.md) | `LensAPI`: конструктор, `process_image`, `process_region`, поля результата, исключения, примеры. |
| [docs/rendering.md](docs/rendering.md) | Рисование перевода на картинке: вертикальный текст, режимы стирания, обводка, режим манги, шрифты. |
| [docs/daemon.md](docs/daemon.md) | Быстрый режим и «тёплый» демон, сервис при входе в систему, HTTP API, модель безопасности. |
| [docs/install.md](docs/install.md) | Все способы установки, контрольные суммы и происхождение сборки, фиксация версии, portable-сборка, Docker. |
| [docs/sharex.md](docs/sharex.md) | Настройка ShareX: два хоткея, режим аплоадера, ручная настройка, решение проблем. |
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
