# Hisense U7QF

Локальная интеграция Hisense 50U7QF для Home Assistant 2026.10+.
Проверена на 50A690FEVS с прошивкой P0219. Поддерживает пульт, громкость,
входы, приложения, настройки изображения, Wake-on-LAN и Audio Only.

## Установка

Через HACS: добавьте `https://github.com/bubylda/hisense-u7qf` как
пользовательский репозиторий типа **Интеграция** и установите **Hisense U7QF**.

Вручную: скопируйте папку `custom_components/hisense_u7qf` в
`/config/custom_components/`.

После установки и перезапуска Home Assistant нажмите кнопку:

[![Добавить в Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hisense_u7qf)

Укажите IP включённого ТВ и введите PIN, если он появится. Интеграцию также можно
добавить через **Настройки → Устройства и службы → Добавить интеграцию → Hisense U7QF**.
При переходе с `hisense_vidaa` сначала отключите старую запись
этого ТВ; ссылки на сущности в автоматизациях потребуется обновить.

## Пульт

В **Инструменты разработчика → Действия** выполните со своим entity_id:

```yaml
action: hisense_u7qf.get_remote_card
target:
  entity_id: media_player.hisense_u7qf
```

Вставьте значение `card` из ответа в ручную карточку панели.

## Особенности

Для Wake-on-LAN нужен MAC-адрес и включённое сетевое пробуждение на ТВ.
Audio Only работает через меню; фактическое состояние экрана не считывается.
Другие модели и режимы HDR/Dolby Vision аппаратно не проверены.
Подключение использует MQTT/TLS и встроенную общую пару сертификата/ключа
RemoteNOW; проверка серверного сертификата отключена.

Основано на [hisense_vidaa](https://github.com/stevene1919/hisense_vidaa).
Лицензия [MIT](LICENSE).
