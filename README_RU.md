# Chrome Lens API для Python

[English](/README.md) | **Русский**

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

> [!IMPORTANT]
> **Масштабное обновление (Версия 3.0.0+)**
> Библиотека была полностью переписана с нуля. Теперь она использует современную асинхронную архитектуру (`async`/`await`) и взаимодействует напрямую с Protobuf эндпоинтом Google для значительно улучшенной надежности и производительности.
>
> **Пожалуйста, обновите ваши проекты. Все вызовы API теперь являются `async`.**

> [!Warning]
> Также обратите внимание, что библиотека была полностью переписана, и я мог что-то пропустить или не указать. Если вы заметили ошибку, сообщите мне в разделе "Issues"

Этот проект предоставляет мощную, асинхронную Python-библиотеку и утилиту командной строки для взаимодействия с Google Lens. Она позволяет выполнять продвинутое распознавание текста (OCR), переводить текст на изображениях и получать точные координаты распознанных слов.

## ✨ Ключевые возможности

-   **Современный бэкенд**: Использует официальный Protobuf-эндпоинт (`v1/crupload`) Google для получения надежных и точных результатов.
-   **Асинхронное ядро**: Построена на `asyncio` и `httpx` для высокопроизводительных, неблокирующих операций.
-   **Мощный OCR**: Извлекает текст с изображений, с опциями сохранения переносов строк или получения текста единой строкой.
-   **Встроенный перевод**: Мгновенно переводите распознанный текст на любой поддерживаемый язык.
-   **Разные источники изображений**: Обрабатывайте изображения из **файла**, по **URL**, из **байтов**, объекта **PIL Image** или массива **NumPy**.
-   **Наложение текста**: Автоматически генерируйте и сохраняйте изображения с наложенным на них переводом(мы с Gemini в процессе изучения того, как сделать наложение лучше).
-   **Функциональный CLI**: Простой, но мощный интерфейс командной строки (`lens_scan`) для быстрого использования.
-   **Поддержка прокси**: Полная поддержка HTTP, HTTPS и SOCKS прокси.
-   **Интеграция с буфером обмена**: Мгновенно копируйте результаты OCR или перевода в буфер обмена с помощью флага `--sharex`.
-   **Гибкая конфигурация**: Управляйте настройками через файл `config.json`, аргументы CLI или переменные окружения.

## 🚀 Установка

Вы можете установить пакет с помощью `pip`:

```bash
pip install chrome-lens-py
```

Чтобы включить функцию копирования в буфер обмена (флаг `--sharex`), установите библиотеку с `[clipboard]` extra:

```bash
pip install "chrome-lens-py[clipboard]"
```

Или установите последнюю версию напрямую с GitHub:
```bash
pip install git+https://github.com/bropines/chrome-lens-py.git
```
## 🚀 Использование


<details>
  <summary><b>🛠️ Использование CLI (`lens_scan`)</b></summary>

  Утилита командной строки предоставляет быстрый доступ к возможностям библиотеки прямо из вашего терминала.

  ```bash
  lens_scan <источник_изображения> [язык_ocr] [опции]
  ```

  -   **`<источник_изображения>`**: Путь к локальному файлу или URL-адрес изображения.
  -   **`[язык_ocr]`** (опционально): Код языка в формате BCP 47 для OCR (например, 'en', 'ja'). Если не указан, API попытается определить язык автоматически.

  #### **Опции**

| Флаг | Алиас | Описание |
| :--- | :--- | :--- |
| `--translate <язык>` | `-t` | **Перевести** распознанный текст на целевой язык (например, `en`, `ru`). |
| `--translate-from <язык>` | | Указать исходный язык для перевода (иначе определяется автоматически). |
| `--translate-out <путь>` | `-to` | **Сохранить** изображение с наложенным переводом по указанному пути. |
| `--get-coords` | | Вывести распознанные слова и их координаты в формате JSON. |
| `--sharex` | `-sx` | **Скопировать** результат в буфер обмена (перевод или OCR). |
| `--ocr-single-line` | | Объединить весь распознанный текст в одну строку, удалив переносы. |
| `--config-file <путь>`| | Путь к кастомному файлу конфигурации в формате JSON. |
| `--update-config` | | Обновить файл конфигурации по умолчанию настройками из текущей команды. |
| `--font <путь>` | | Путь к файлу шрифта `.ttf` для наложения текста. |
| `--font-size <размер>` | | Размер шрифта для наложения (по умолчанию: 20). |
| `--proxy <url>` | | URL прокси-сервера (например, `socks5://127.0.0.1:9050`). |
| `--logging-level <ур>`| `-l` | Установить уровень логирования (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `--help` | `-h` | Показать это справочное сообщение. |

  #### **Примеры**

  1.  **Распознать текст на картинке (автоопределение языка) и перевести на английский:**
      ```bash
      lens_scan "путь/к/вашему/изображению.png" -t en
      ```

  2.  **Распознать японский текст, перевести на русский, сохранить результат и скопировать в буфер обмена:**
      ```bash
      lens_scan "путь/к/манге.jpg" ja -t ru -to "перевод_манги.png" -sx
      ```
  
  3.  **Получить координаты всех слов в формате JSON:**
      ```bash
      lens_scan "путь/к/схеме.png" --get-coords
      ```
  
  4.  **Обработать изображение по URL и получить текст OCR в одну строку:**
      ```bash
      lens_scan "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
      ```


</details>

<details>
  <summary><b>👨‍💻 Программное использование (API)</b></summary>
  
  > [!IMPORTANT]
  > `LensAPI` полностью **асинхронный**. Все методы для получения данных должны вызываться с помощью `await` из `async` функции.

  #### **Базовый пример**
  
  Этот пример показывает, как инициализировать API, обработать изображение и вывести результаты.

  ```python
  import asyncio
  from chrome_lens_py.api import LensAPI
  from chrome_lens_py.constants import DEFAULT_API_KEY

  async def main():
      # Инициализируем API с вашим ключом.
      # Здесь также можно передать прокси, регион и другие параметры.
      api = LensAPI(api_key=DEFAULT_API_KEY)

      image_source = "путь/к/вашему/изображению.png" # Или URL, PIL Image, NumPy array

      try:
          # Обрабатываем изображение и запрашиваем перевод
          result = await api.process_image(
              image_path=image_source,
              ocr_language="ja", # Опционально, можно опустить для автоопределения
              target_translation_language="en"
          )

          print("--- Распознанный текст (OCR) ---")
          print(result.get("ocr_text"))

          print("\n--- Переведенный текст ---")
          print(result.get("translated_text"))

          # Вывод данных о словах и их координатах
          # print("\n--- Данные о словах ---")
          # import json
          # print(json.dumps(result.get("word_data"), indent=2, ensure_ascii=False))
          
      except Exception as e:
          print(f"Произошла ошибка: {e}")

  if __name__ == "__main__":
      asyncio.run(main())
  ```
  
  #### **Работа с разными источниками изображений**

  Метод `process_image` легко обрабатывает различные типы входных данных.

  ```python
  from PIL import Image
  import numpy as np

  # ... внутри async функции ...
  
  # Из URL
  result_url = await api.process_image("https://i.imgur.com/VPd1y6b.png")

  # Из объекта PIL Image
  with Image.open("путь/к/изображению.png") as img:
      result_pil = await api.process_image(img)

  # Из массива NumPy (например, загруженного через OpenCV)
  with Image.open("путь/к/изображению.png") as img:
      numpy_array = np.array(img)
      result_numpy = await api.process_image(numpy_array)
  ```

  #### **Конструктор `LensAPI`**

  ```python
  api = LensAPI(
      api_key: str,
      client_region: Optional[str] = None,
      client_time_zone: Optional[str] = None,
      proxy: Optional[str] = None,
      timeout: int = 60,
      font_path: Optional[str] = None,
      font_size: Optional[int] = None
  )
  ```

  #### **Метод `process_image`**
  
  ```python
  result: dict = await api.process_image(
      image_path: Any,
      ocr_language: Optional[str] = None,
      target_translation_language: Optional[str] = None,
      source_translation_language: Optional[str] = None,
      output_overlay_path: Optional[str] = None,
      new_session: bool = True,
      ocr_preserve_line_breaks: bool = True
  )
  ```
  -   **`ocr_preserve_line_breaks`**: Если `False`, объединяет весь текст OCR в одну строку.
  -   **`new_session`**: Если `False`, пытается использовать ту же серверную сессию, что и предыдущий запрос.

  **Возвращаемый словарь `result` содержит:**
  - `ocr_text` (str): Полный распознанный текст.
  - `translated_text` (Optional[str]): Переведенный текст, если был запрошен.
  - `word_data` (List[dict]): Список словарей, где каждый словарь содержит информацию о распознанном слове: `word`, `separator` и `geometry` (координаты, угол и т.д.).
  - `raw_response_objects` (LensOverlayObjectsResponse): "Сырой" Protobuf-объект ответа для дальнейшего анализа.

</details>

<details>
  <summary><b>⚙️ Конфигурация</b></summary>
  
  Настройки загружаются со следующим приоритетом: **Аргументы CLI > Файл `config.json` > Значения по умолчанию**.
  
  #### **`config.json`**
  
  Файл `config.json` можно разместить в директории конфигурации по умолчанию вашей ОС для установки постоянных опций.
  -   **Linux**: `~/.config/chrome-lens-py/config.json`
  -   **macOS**: `~/Library/Application Support/chrome-lens-py/config.json`
  -   **Windows**: `C:\Users\<user>\.config\chrome-lens-py\config.json`

  ##### **Пример `config.json`**
  ```json
  {
    "api_key": "ОПЦИОНАЛЬНО! Если вы не знаете что это, то не советую его здесь указывать",
    "proxy": "socks5://127.0.0.1:9050",
    "client_region": "DE",
    "client_time_zone": "Europe/Berlin",
    "timeout": 90,
    "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "ocr_preserve_line_breaks": true
  }
  ```

</details>

## Интеграция Sharex
Посмотрите [sharex.md](docs/sharex.md) для получения дополнительной информации о том, как использовать эту библиотеку с ShareX.

## ❤️ Поддержка и благодарности

-   **OWOCR** В большей степени вдохновлен и основан на [OWOCR](https://github.com/AuroraWright/owocr). Благодарю ребят, за их ресерч protobuf и реализацию OCR.
-   **Chrome Lens OCR**: За изначальную реализацию и идеи, которые легли в основу этой библиотеки. Обновление с поддержкой SHAREX изначально было протестировано и добавлено мной в [chrome-lens-ocr](https://github.com/dimdenGD/chrome-lens-ocr), спасибо за изначальную реализацию и идеи.
-   **Совместная работа с ИИ**: Значительная часть кода версии 3.0, включая рефакторинг архитектуры, асинхронную реализацию и интеграцию с Protobuf, была разработана в сотрудничестве с продвинутым ИИ-ассистентом.
-   **GOOGLE**: За удобную и качественную технологию Lens.
-   **Поддержать автора**: Если эта библиотека оказалась вам полезной, вы можете поддержать автора - **[Boosty](https://boosty.to/pinus)**

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bropines/chrome-lens-py&type=Date)](https://www.star-history.com/#bropines/chrome-lens-py&Date)

### Отказ от ответственности

Этот проект предназначен исключительно для образовательных и экспериментальных целей. Использование сервисов Google должно соответствовать их Условиям предоставления услуг. Автор проекта не несет ответственности за любое неправомерное использование этого программного обеспечения.
