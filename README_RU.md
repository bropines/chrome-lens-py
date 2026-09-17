# Chrome Lens API для Python

[English](/README.md) | **Русский**

[![PyPI version](https://badge.fury.io/py/chrome-lens-py.svg)](https://badge.fury.io/py/chrome-lens-py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/chrome-lens-py.svg)](https://pypi.org/project/chrome-lens-py)
[![Downloads](https://static.pepy.tech/badge/chrome-lens-py)](https://pepy.tech/project/chrome-lens-py)

> [!IMPORTANT]
> **Масштабное обновление (Версия 3.1.0+)**
> Библиотека была полностью переписана с нуля. Теперь она использует современную асинхронную архитектуру (`async`/`await`) и взаимодействует напрямую с Protobuf эндпоинтом Google для значительно улучшенной надежности и производительности.
>
> **Пожалуйста, обновите ваши проекты. Все вызовы API теперь являются `async`.**

> [!Warning]
> Также обратите внимание, что библиотека была полностью переписана, и я мог что-то пропустить или не указать. Если вы заметили ошибку, сообщите мне в разделе "Issues"

Этот проект предоставляет мощную, асинхронную Python-библиотеку и утилиту командной строки для взаимодействия с Google Lens. Она позволяет выполнять продвинутое распознавание текста (OCR), получать сегментированные текстовые блоки (например, для комиксов), переводить текст и получать точные координаты слов.

## 🚀 Быстрый старт для пользователей Windows

Если вы не хотите устанавливать Python, вы можете скачать готовый файл **lens_scan-windows-amd64.exe** из раздела [Releases](https://github.com/bropines/chrome-lens-py/releases).

> [!WARNING]
> **Ложные срабатывания антивируса**: Некоторые антивирусы (например, Windows Defender) могут помечать скомпилированный `.exe` как угрозу (например, `Trojan:Win32/Wacatac.H!ml`). Это **ложное срабатывание**, характерное для бинарных файлов Nuitka/PyInstaller. Проект имеет открытый исходный код; вы можете изучить его и собрать файл самостоятельно, если у вас есть сомнения.

### 📸 Автоматическая настройка ShareX
Если вы используете **ShareX**, вы можете полностью автоматизировать настройку одной командой:
```bash
# Через установленный пакет:
lens_scan --setup-sharex

# Или через готовый .exe файл:
lens_scan-windows-amd64.exe --setup-sharex
```
Это автоматически настроит горячую клавишу (**Ctrl + O**) и все необходимые действия для использования Google Lens OCR.

---

## ✨ Ключевые возможности

-   **Современный бэкенд**: Использует официальный Protobuf-эндпоинт (`v1/crupload`) Google для получения надежных и точных результатов.
-   **Асинхронность и безопасность**: Построена на `asyncio` и `httpx`. Включает встроенный семафор для предотвращения злоупотреблений API и банов IP-адресов из-за чрезмерного количества одновременных запросов.
-   **Мощный OCR и сегментация**:
    -   Извлекайте текст с изображений в виде единой строки.
    -   Получайте текст, разделенный на логические блоки (абзацы, диалоговые окна) с их собственными координатами.
    -   Получайте отдельные строки текста с их собственной точной геометрией.
-   **Встроенный перевод**: Мгновенно переводите распознанный текст на любой поддерживаемый язык.
-   **Разные источники изображений**: Обрабатывайте изображения из **файла**, по **URL**, из **байтов**, объекта **PIL Image** или массива **NumPy**.
-   **Наложение текста**: Рендер перевода прямо на картинку по тому же алгоритму, что и оверлей Google Lens в Chromium: подбор кегля бинарным поиском по боксу шрифта, геометрия строки берётся у исходной строки, фон — серверный inpaint. Плюс вертикальный японский, режим для манги, обводка и выравнивание.
-   **Функциональный CLI**: Простой, но мощный интерфейс командной строки (`lens_scan`) для быстрого использования.
-   **Поддержка прокси**: Полная поддержка HTTP, HTTPS и SOCKS прокси.
-   **Интеграция с буфером обмена**: Мгновенно копируйте результаты OCR или перевода в буфер обмена с помощью флага `--sharex`.
-   **Гибкая конфигурация**: Управляйте настройками через файл `config.json`, аргументы CLI или переменные окружения.

## 🚀 Установка

Четыре пути, отличаются тем, что требуют от вас:

| | нужен Python? | как | обновление |
|---|---|---|---|
| **Homebrew** (macOS, Linux) | нет | `brew install bropines/tap/lens-scan` | `brew upgrade lens-scan` |
| **uv** | нет — uv притащит свой | `install-uv.ps1` / `install-uv.sh` | `uv tool upgrade chrome-lens-py` |
| **standalone zip** | нет | `install.ps1` / `install.sh` | перезапустить установщик |
| **pip** | да, свой | `pip install chrome-lens-py` | `pip install -U chrome-lens-py` |

### Homebrew

```bash
brew install bropines/tap/lens-scan
```

Это одна команда, а не две: `brew` по пути сам подключит тап
[bropines/homebrew-tap](https://github.com/bropines/homebrew-tap). Ставится
готовая standalone-сборка, поэтому какой у вас Python — неважно, а формула
обновляется автоматически на каждом релизе.

Собираются Apple Silicon и x86_64 Linux. На Intel-маке или ARM-линуксе формула
не станет качать то, чего не собирали, а остановится и отправит к uv.

### Однострочник через uv

Ставит uv, если его нет, затем ставит `lens_scan` как uv-инструмент и кладёт в
PATH. Ничего не заморожено в исполняемый файл — значит, эвристикам антивируса
не на что реагировать; Python заранее не нужен, uv принесёт свой.

```powershell
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.ps1 | iex
```

```bash
curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install-uv.sh | sh
```

Ставится вместе с extra `[clipboard]`, чтобы `--sharex` работал сразу.

```bash
uv tool upgrade chrome-lens-py      # обновиться потом
uv tool uninstall chrome-lens-py
```

> **Если `lens_scan` на PATH уже есть** — например, pip-установка за шимом
> pyenv или старая standalone-сборка — она может стоять раньше и продолжит
> выигрывать после установки. Установщик предупредит, если это заметит.
> `lens_scan --version` печатает путь, откуда он реально запустился.

### Если Python уже есть

```bash
uv tool install "chrome-lens-py[clipboard]"
pip install chrome-lens-py
```

Дополнительные extras:

```bash
pip install "chrome-lens-py[clipboard]"  # буфер обмена, флаг --sharex
pip install "chrome-lens-py[rtl]"        # арабский/иврит: шейпинг и bidi
pip install "chrome-lens-py[fonts]"      # fontTools, подбор шрифта по символам
```

Или последняя версия прямо с GitHub:
```bash
pip install git+https://github.com/bropines/chrome-lens-py.git
```

### Если Python нет: standalone одной строкой

Скачивает последний релиз, **проверяет SHA-256**, распаковывает, кладёт
`lens_scan` в PATH и убеждается, что бинарь стартует.

```powershell
irm https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.ps1 | iex
```

```bash
curl -fsSL https://raw.githubusercontent.com/bropines/chrome-lens-py/main/scripts/install.sh | sh
```

Ставится в `%LOCALAPPDATA%\Programs\lens-scan` или `~/.local/share/lens-scan`.

К каждому архиву в релизе лежит `.sha256`, установщики сверяют его до
распаковки. Проверить руками:

```bash
sha256sum -c lens_scan-linux-amd64.zip.sha256
```

Стоит понимать, что именно это даёт: ловит битую или недокачанную загрузку и
CDN, отдавший не то, что загружали. Это не подпись — тот, кто может переписать
релиз, перепишет и контрольную сумму.

### Какая копия запускается

Имя `lens_scan` могут занимать сразу несколько установок — pip, `uv tool`,
editable-чекаут и standalone-сборка. Чтобы не гадать:

```bash
lens_scan --version
```

Печатает версию, откуда она загружена (пакет, исходники, standalone), путь до
интерпретатора и до самого пакета.
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
| `--output-blocks` | `-b` | **Вывести текст OCR в виде сегментированных блоков** (полезно для комиксов). Несовместимо с `--get-coords` и `--output-lines`.|
| `--output-lines` | `-ol` | **Вывести текст OCR в виде отдельных строк** с их геометрией. Несовместимо с `--output-blocks` и `--get-coords`.|
| `--get-coords` | | Вывести распознанные слова и их координаты в формате JSON. Несовместимо с `--output-blocks` и `--output-lines`.|
| `--sharex` | `-sx` | **Скопировать** результат в буфер обмена (перевод или OCR). |
| `--ocr-single-line` | | Объединить весь распознанный текст в одну строку, удалив переносы. |
| `--config-file <путь>`| | Путь к кастомному файлу конфигурации в формате JSON. |
| `--update-config` | | Обновить файл конфигурации по умолчанию настройками из текущей команды. |
| `--font <путь>` | | Путь к файлу шрифта `.ttf` для наложения текста. |
| `--font-size <размер>` | | Размер шрифта для наложения (по умолчанию: 20). |
| `--proxy <url>` | | URL прокси-сервера (например, `socks5://127.0.0.1:9050`). |
| `--no-env-proxy` | | Игнорировать `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` из окружения и идти напрямую. |
| `--concurrency <N>` | | Максимум одновременных запросов (по умолчанию 5, потолок 30). |
| `--timeout <сек>` | | Таймаут запроса в секундах (по умолчанию 60). |
| `--overlay-mode <режим>`| | `chromium` (по умолчанию) или `legacy` — старое наложение белым боксом. |
| `--vertical-text <режим>`| | Вертикальный CJK: `auto`, `keep` или `horizontal`. |
| `--erase-mode <режим>` | | `patch` (серверный inpaint) или `hull` (залить область целиком). |
| `--hull-padding <N>` | | Отступ оболочки за текст, в долях высоты строки. |
| `--outline <N>` | | Множитель обводки под текстом; `0` убирает. |
| `--min-text-size <px>` | | Нижняя граница кегля для читаемости. |
| `--text-align <сторона>`| | `auto`, `left`, `center` или `right`. |
| `--manga` | | Пресет для вертикальной манги (см. раздел о рендеринге). |
| `--manga-growth <N>` | | Насколько шире бокса раскладывать в режиме манги. |
| `--region <cx,cy,w,h>` | | Перечитать одну область в исходном разрешении (доли 0..1). |
| `--text-query <текст>` | | Текст-вопрос вместе с `--region`. |
| `--serve` | | Запустить локальный HTTP-демон вместо обработки картинки. |
| `--host <адрес>` | | Адрес для демона (по умолчанию `127.0.0.1`). |
| `--port <N>` | | Порт для демона (по умолчанию `8765`). |
| `--token <токен>` | | Требовать bearer-токен. Обязателен, если `--host` не loopback. |
| `--allow-origin <origin>`| | Пустить один браузерный origin к демону (можно повторять). По умолчанию ни одного. |
| `--setup-sharex` | | Автоматически прописать `lens_scan` в ShareX. |
| `--logging-level <ур>`| `-l` | Установить уровень логирования (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `--version` | `-V` | Показать версию и то, какая именно копия запускается. |
| `--help` | `-h` | Показать это справочное сообщение. |

  #### **Примеры**

  **1. Базовое распознавание (OCR) и перевод**
  
  Автоматически определяет язык на изображении и переводит его на английский. Это самый распространенный сценарий использования.
  ```bash
  lens_scan "путь/к/вашему/изображению.png" -t en
  ```

  ---
  
  **2. Получение сегментированных текстовых блоков (для комиксов/манги)**

  Идеально подходит для изображений с несколькими отдельными текстовыми блоками. Эта команда выводит каждый распознанный блок текста по отдельности, что отлично подходит для перевода комиксов или сложных документов.
  ```bash
  lens_scan "путь/к/манге.jpg" ja -b
  ```
  - `-b` — это короткий псевдоним для `--output-blocks`.

  ---
  
  **3. Получение отдельных строк текста**
  
  Выводит каждую распознанную строку текста вместе с ее геометрией.
  ```bash
  lens_scan "путь/к/документу.png" --output-lines
  ```
  - `-ol` — это короткий псевдоним для `--output-lines`.
  
  ---

  **4. Получение координат всех отдельных слов**
  
  Выводит подробный массив JSON, содержащий каждое распознанное слово и его точные геометрические данные (центр, размер, угол). Полезно для программного анализа или создания собственных наложений.
  ```bash
  lens_scan "путь/к/схеме.png" --get-coords
  ```
  
  ---

  **5. Перевести, сохранить с наложением и скопировать в буфер обмена**
  
  Пример для продвинутых пользователей. Эта команда выполнит несколько действий:
  1. Распознает текст на японском изображении.
  2. Переведет его на русский.
  3. Сохранит новое изображение `перевод_манги.png` с наложенным на него русским текстом.
  4. Скопирует итоговый перевод в буфер обмена.
  ```bash
  lens_scan "путь/к/манге.jpg" ja -t ru -to "перевод_манги.png" -sx
  ```

  ---

  **6. Обработать изображение по URL и получить текст в одну строку**

  Загружает изображение напрямую по URL-адресу и объединяет весь распознанный текст в одну непрерывную строку, удаляя все переносы.
  ```bash
  lens_scan "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
  ```

  ---

  **7. Использовать SOCKS5 прокси**
  
  Все запросы к API Google будут направляться через указанный прокси-сервер, что полезно для обеспечения конфиденциальности или обхода региональных ограничений.
  ```bash
  lens_scan "image.png" --proxy "socks5://127.0.0.1:9050"
  ```


</details>

<details>
  <summary><b>👨‍💻 Программное использование (API)</b></summary>
  
  > [!IMPORTANT]
  > `LensAPI` полностью **асинхронный**. Все методы для получения данных должны вызываться с помощью `await` из `async` функции.

  #### **Базовый пример (Полный текст)**
  
  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def main():
      # Инициализируем API. Здесь можно передать прокси, регион и т.д.
      # По умолчанию API ключ не требуется.
      api = LensAPI()

      image_source = "путь/к/вашему/изображению.png" # Или URL, PIL Image, NumPy array

      try:
          # Обрабатываем изображение и получаем текст единой строкой
          result = await api.process_image(
              image_path=image_source,
              ocr_language="ja",
              target_translation_language="en"
          )

          print("--- Распознанный текст (OCR) ---")
          print(result.get("ocr_text"))

          print("\n--- Переведенный текст ---")
          print(result.get("translated_text"))
          
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
  
  #### **Получение сегментированных текстовых блоков**

  Чтобы получить текст, разделенный на логические блоки (например, диалоговые окна в комиксе), используйте параметр `output_format='blocks'`.

  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def process_comics():
      api = LensAPI()
      image_source = "путь/к/манге.jpg"
      
      result = await api.process_image(
          image_path=image_source,
          output_format='blocks' # Получить сегментированные блоки вместо одной строки
      )

      # Результат теперь содержит ключ 'text_blocks'
      text_blocks = result.get("text_blocks", [])
      print(f"Найдено {len(text_blocks)} текстовых блоков.")

      for i, block in enumerate(text_blocks):
          print(f"\n--- Блок #{i+1} ---")
          print(block['text'])
          # block также содержит ключи 'lines' и 'geometry'
  
  asyncio.run(process_comics())
  ```

  #### **Получение отдельных строк и их геометрии**

  Чтобы получить каждую распознанную строку текста как отдельный элемент, используйте параметр `output_format='lines'`.

  ```python
  import asyncio
  from chrome_lens_py import LensAPI

  async def process_document_lines():
      api = LensAPI()
      image_source = "путь/к/документу.png"
      
      result = await api.process_image(
          image_path=image_source,
          output_format='lines' # Получить отдельные строки с их геометрией
      )

      # Результат теперь содержит ключ 'line_blocks'
      line_blocks = result.get("line_blocks", [])
      print(f"Найдено {len(line_blocks)} строк.")

      for i, line in enumerate(line_blocks):
          print(f"\n--- Строка #{i+1} ---")
          print(f"Текст: {line['text']}")
          print(f"Геометрия: {line['geometry']}")
  
  asyncio.run(process_document_lines())
  ```
#### **Получение полностью детализированных структур текста**

Чтобы получить полную, вложенную структуру из абзацев, строк и слов с геометрией на каждом уровне, используйте `output_format='detailed'`.

```python
import asyncio
from chrome_lens_py import LensAPI

async def process_with_details():
    api = LensAPI()
    image_source = "путь/к/документу.png"
    
    result = await api.process_image(
        image_path=image_source,
        output_format='detailed' # Получить полностью вложенную структуру
    )

    # Результат теперь содержит ключ 'detailed_blocks'
    detailed_blocks = result.get("detailed_blocks", [])
    print(f"Найдено {len(detailed_blocks)} детализированных блоков.")

    for i, block in enumerate(detailed_blocks):
        print(f"\n--- Блок #{i+1} ---")
        print(f"  Геометрия: {block['geometry']}")
        for j, line in enumerate(block['lines']):
            print(f"    --- Строка #{j+1}: '{line['text']}' ---")
            for k, word in enumerate(line['words']):
                 print(f"      - Слово: '{word['text']}', Геометрия: {word['geometry']}")

asyncio.run(process_with_details())
```


  #### **Конструктор `LensAPI`**

  ```python
  api = LensAPI(
      api_key: str = "ВАШ_API_КЛЮЧ_ИЛИ_КЛЮЧ_ПО_УМОЛЧАНИЮ",
      client_region: Optional[str] = None,
      client_time_zone: Optional[str] = None,
      proxy: Optional[str] = None,
      timeout: int = 60,
      font_path: Optional[str] = None,
      font_size: Optional[int] = None,
      max_concurrent: int = 5,
      trust_env: bool = True,
  )
  ```
  -   **`trust_env`**: Учитывать ли `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` из окружения. Поставьте `False`, если запросы намертво виснут из-за забытой переменной прокси — именно это было причиной жалоб «работает только с включённым прокси».

  `LensAPI` — асинхронный контекстный менеджер, закрытие возвращает соединения
  из пула:

  ```python
  async with LensAPI() as api:
      ...
  # либо: api = LensAPI(); ...; await api.aclose()
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
      ocr_preserve_line_breaks: bool = True,
      output_format: Literal['full_text', 'blocks', 'lines', 'detailed'] = 'full_text',
      # рендер наложения; за что отвечает каждый — в разделе о рендеринге
      overlay_mode: Literal['chromium', 'legacy'] = 'chromium',
      vertical_text: Literal['keep', 'auto', 'horizontal'] = 'auto',
      erase_mode: Literal['patch', 'hull'] = 'patch',
      hull_padding: float = 0.45,
      outline_scale: float = 1.0,
      min_readable_px: float = 0.0,
      text_align: Literal['auto', 'left', 'center', 'right'] = 'auto',
      manga_mode: bool = False,
      manga_box_growth: float = 1.45,
      include_raw_response: bool = False,
  )
  ```
  -   **`output_format`**: Управляет структурой OCR-вывода. `'full_text'` (по умолчанию) возвращает одну строку в `ocr_text`. `'blocks'` возвращает список в `text_blocks`. `'lines'` возвращает список в `line_blocks`. `'detailed'` возвращает полностью вложенную структуру в `detailed_blocks`.
  -   **`ocr_preserve_line_breaks`**: Если `False` и `output_format` равен `'full_text'`, объединяет весь текст OCR в одну строку.
  -   **`include_raw_response`**: По умолчанию выключен. Сырые protobuf-объекты большие и не сериализуются, поэтому прикладываются только по запросу.
  -   Параметры рендера имеют смысл только вместе с `output_overlay_path`. У каждого есть одноимённый флаг CLI — см. [Рендеринг перевода](#-рендеринг-перевода).

  **Возвращаемый словарь `result` содержит:**
  - `ocr_text` (Optional[str]): Полный распознанный текст (если `output_format='full_text'`).
  - `text_blocks` (Optional[List[dict]]): Список сегментированных текстовых блоков (если `output_format='blocks'`). Каждый блок — это словарь с ключами `text`, `lines` и `geometry`.
  - `line_blocks` (Optional[List[dict]]): Список отдельных текстовых строк (если `output_format='lines'`). Каждый блок — это словарь с ключами `text` и `geometry`.
  - `translated_text` (Optional[str]): Переведенный текст, если был запрошен.
  - `word_data` (List[dict]): Список словарей для каждого распознанного слова с его геометрией.
  - `detailed_blocks` (Optional[List[dict]]): Список полностью структурированных текстовых блоков (если `output_format='detailed'`). Каждый блок содержит строки, которые, в свою очередь, содержат слова, с геометрией на каждом уровне.
  - `raw_response_objects`: "Сырой" Protobuf-объект ответа — **только при `include_raw_response=True`**.

  #### **Метод `process_region`**

  ```python
  result: dict = await api.process_region(
      image_path: Any,
      region: Tuple[float, float, float, float],   # center_x, center_y, w, h
      ocr_language: Optional[str] = None,
      text_query: Optional[str] = None,
      ocr_preserve_line_breaks: bool = True,
  )
  ```
  Перечитывает одну область в исходном разрешении. См. [Запрос по области](#-запрос-по-области).

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

## 🖥️ Режим демона

Импорт Pillow, protobuf и httpx стоит около секунды. Если `lens_scan` вызывается
часто — например, ShareX на каждый скриншот — этот импорт можно оплатить один раз:

```bash
lens_scan --serve                      # http://127.0.0.1:8765
lens_scan --serve --port 9000 --token secret
```

| маршрут | тело запроса |
|---|---|
| `POST /v1/ocr` | `{"image": "<путь или URL>"}` либо `{"image_b64": "..."}`, плюс любые из `translate_to`, `translate_from`, `ocr_language`, `ocr_preserve_line_breaks`, `output_format`, `overlay_path`, `overlay_mode`, `vertical_text`, `erase_mode`, `hull_padding`, `outline_scale`, `min_readable_px`, `text_align`, `manga_mode`, `manga_box_growth` |
| `POST /v1/region` | тот же источник, плюс `"region": [center_x, center_y, width, height]` в долях 0..1 и необязательный `text_query` |
| `GET /health` | проверка живости, отдаёт версию |

Все опции рендеринга, что есть в CLI, принимаются здесь под теми же именами:
`--erase-mode hull --outline 3` в командной строке — это `"erase_mode": "hull",
"outline_scale": 3` в теле. Запросы обязаны быть `Content-Type: application/json`.

### Кто может до него достучаться

Демон держит API-ключ и сходит в Google за любого, кто до него дозвонился,
поэтому по умолчанию он закрыт:

- **Ни одна веб-страница им не воспользуется.** Запрос с заголовком `Origin`
  отклоняется, если этот origin не указан в `--allow-origin`. Проверяется именно
  *запрос*, а не ответ: страница может отправить POST, который ей запрещено
  прочитать, и всё равно получить нужный ей побочный эффект — запрос к Google на
  ваш ключ или открытый файл с вашего диска.
- **`--host` вне loopback требует `--token`**, и тогда принимается только
  `image_b64`. Путь или URL — это то, что демон открывает сам: на сетевом
  слушателе это чтение вашего диска и поход на хост по выбору вызывающего.
- Токен сравнивается за постоянное время.

```bash
# открыть одной своей странице
lens_scan --serve --allow-origin https://yoursite.example

# наружу: токен обязателен, принимаются только пиксели
lens_scan --serve --host 0.0.0.0 --token "$(openssl rand -hex 24)"
```

Userscript'у для Tampermonkey всё это **не нужно** — он ходит в Google напрямую
через `GM_xmlhttpRequest`, на который CORS не распространяется. Открывать демон
браузерному origin'у имеет смысл только для страниц, которые вы пишете сами.

## 🔍 Запрос по области

Полнокадровый проход ужимает всё, что больше 1600px, — ровно там, где мелкий
текст и страдает. Запрос по области отправляет только вырезанные пиксели, в
исходном масштабе:

```python
async with LensAPI() as api:
    # (center_x, center_y, width, height) в долях от полного изображения
    result = await api.process_region("page.png", (0.8, 0.82, 0.35, 0.06))
    print(result["ocr_text"])
```

```bash
lens_scan page.png --region 0.8,0.82,0.35,0.06
lens_scan page.png --region 0.8,0.82,0.35,0.06 --text-query "что тут написано"
```

Геометрия возвращается в координатах полного изображения, так что напрямую
сопоставима с выводом `process_image`.

## 🎨 Рендеринг перевода

```bash
lens_scan manga.png -t ru -to out.png                      # как в Chromium, по умолчанию
lens_scan manga.png -t ru -to out.png --vertical-text horizontal
lens_scan page.png  -t ru -to out.png --overlay-mode legacy
```

`--vertical-text` решает судьбу вертикального CJK-текста:

| значение | поведение |
|---|---|
| `auto` (по умолчанию) | остаётся вертикальным, только если переводим в CJK-язык |
| `keep` | всегда вертикально, ровно как Chromium |
| `horizontal` | абзац переливается в горизонтальные строки с переносами |

### Чтобы результат читался

Chromium перерисовывает строку в тот же бокс, где была исходная. Для дорожного
знака это верно, для облачка в манге — нет: перевод заметно длиннее японского,
который он заменяет. Эти ручки существуют ради этого разрыва:

| флаг | параметр API | что делает |
|---|---|---|
| `--erase-mode patch\|hull` | `erase_mode` | `patch` — серверный inpaint, как в Chromium. `hull` — обводит область текста выпуклой оболочкой и заливает цветом фона: чище, но только там, где этот цвет ровный. |
| `--hull-padding N` | `hull_padding` | Насколько оболочка выходит за текст, в долях высоты строки (по умолчанию `0.45`). |
| `--outline N` | `outline_scale` | Множитель обводки под переведённым текстом; `0` убирает её. Рисуется настоящим штрихом, поэтому остаётся чистой вплоть до `8`. |
| `--min-text-size PX` | `min_readable_px` | Нижняя граница кегля. Увеличение текста **не** увеличивает стираемую область — она меряется по тексту как он реально нарисован. |
| `--text-align auto\|left\|center\|right` | `text_align` | `auto` повторяет исходную строку. |
| `--manga` | `manga_mode` | Пресет для страниц вертикального японского: всегда переливать, раскладывать шире найденного бокса, стирать оболочкой, крупнее минимальный размер. |
| `--manga-growth N` | `manga_box_growth` | Насколько шире найденного бокса раскладывать в режиме манги (по умолчанию `1.45`). |

```bash
lens_scan page.png -t ru -to out.png --manga
lens_scan page.png -t ru -to out.png --erase-mode hull --outline 3 --min-text-size 18
```

Для языков справа налево (арабский, иврит, фарси…) нужен шейпинг, которого нет в
опубликованных колёсах Pillow — они собраны без libraqm:

```bash
pip install "chrome-lens-py[rtl]"      # python-bidi + arabic-reshaper
pip install "chrome-lens-py[fonts]"    # fontTools, подбор шрифта по символам
```

Без extra `fonts` рендер работает, но шрифт без нужных глифов нарисует «тофу».

## Интеграция Sharex
Посмотрите [sharex.md](docs/sharex.md) для получения дополнительной информации о том, как использовать эту библиотеку с ShareX.

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