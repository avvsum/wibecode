# KayKit: единый мультяшный мир

Оригинальные бесплатные наборы [Kay Lousberg](https://kaylousberg.com/),
лицензия **CC0 1.0**. Модели можно использовать и распространять вместе
с приложением, в том числе коммерческим. Авторство Kay Lousberg сохраняем
в этой документации; оригинальная лицензия находится в каждой папке.

| Папка | Набор | Содержимое glTF/GLB |
|---|---|---:|
| `adventurers` | [Adventurers Free 2.0](https://kaylousberg.itch.io/kaykit-adventurers) | 5 персонажей + вариант Rogue с капюшоном, 31 аксессуар, 2 набора анимаций |
| `animations` | [Character Animations Free 1.1](https://kaylousberg.itch.io/kaykit-character-animations) | 14 наборов анимаций, 2 манекена |
| `furniture` | [Furniture Bits 1.0](https://github.com/KayKit-Game-Assets/KayKit-Furniture-Bits-1.0) | 53 модели |
| `forest` | [Forest Nature Free 1.0](https://kaylousberg.itch.io/kaykit-forest) | 105 моделей |
| `dungeon` | [Dungeon Remastered 1.0](https://github.com/KayKit-Game-Assets/KayKit-Dungeon-Remastered-1.0) | 203 модели |
| `space` | [Space Base Bits 1.0](https://github.com/KayKit-Game-Assets/KayKit-Space-Base-Bits-1.0) | 57 моделей |
| `city` | [City Builder Bits 1.0](https://github.com/KayKit-Game-Assets/KayKit-City-Builder-Bits-1.0) | 41 модель |

Включены все модели бесплатных версий перечисленных наборов в формате
glTF/GLB, их бинарные буферы и текстуры. FBX, OBJ, Unity/Godot-проекты,
платные EXTRA и SOURCE в репозиторий не добавлены. Суммарно: **459 моделей
окружения** и персонажи с аксессуарами и анимациями; исходные файлы занимают
около **30,7 MiB**.

`manifest.json` содержит полный список файлов с размером и SHA-256,
списки моделей и происхождение. Для GitHub зафиксирована ревизия;
для официальных itch.io-архивов — имя версии и SHA-256 скачанного архива.
Дата получения: 25 октября 2026 года.

Персонажи находятся в `adventurers/Characters/gltf/`. В текущей версии 2.0
их GLB содержат модель и скелет. Анимации лежат отдельно:
`animations/Animations/gltf/Rig_Medium/`; их требуется назначать
совместимому скелету. Наличие анимации в наборе не означает, что каждое
движение уже доступно из сценария приложения.
