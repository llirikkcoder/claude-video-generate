# Библиотека стилей

Пресеты дописываются к пользовательскому сюжету. Применил пресет — скажи какой, чтобы можно было отменить.

Формат промпта, который работает у всех перечисленных моделей: **сюжет → композиция → свет → материал и фактура → оптика → палитра → настроение**. Порядок важнее пышности прилагательных.

## Пресеты

**`product-clean`** — карточка товара
> centered subject on seamless off-white backdrop, soft large-source lighting from upper left, gentle contact shadow, no props, 85mm lens, f/5.6, colour-accurate, commercial product photography

**`interior-warm`** — картина на стене в интерьере
> framed artwork on a plain wall, warm afternoon daylight from a window out of frame, shallow depth of field on the wall texture, natural colour, 35mm, unstyled lived-in room, no people

**`editorial-moody`** — обложка, атмосферный кадр
> single subject, low-key lighting with one hard key and deep falloff, muted desaturated palette, film grain, 50mm, shot on medium format, quiet and restrained

**`flat-vector`** — иконки, иллюстрации
> flat vector illustration, limited palette of four colours, thick uniform strokes, no gradients, generous negative space, geometric construction

**`texture-macro`** — фактура холста, мазок
> extreme macro of paint surface, raking light across impasto ridges, visible canvas weave, no subject matter, abstract field, 100mm macro, f/8

**`social-square`** — пост в ленту
> square 1:1 composition, subject offset to the right third, clean upper area left empty for text overlay, bright even lighting, high contrast, thumb-stopping

## Соотношения сторон

| Куда | Пропорция | Заметка |
|---|---|---|
| Карточка товара | 1:1 или 4:5 | 4:5 занимает больше экрана в ленте |
| Обложка сайта | 16:9 | |
| Сторис, рилс | 9:16 | |
| Печать A-формата | 1:1.414 | нет пресета — задавай `{width,height}` руками |

## Что не писать в промпт

- Имя ныне живущего художника как указание стиля — вместо «в стиле такого-то» опиши признаки: палитру, мазок, композицию, материал.
- Имена реальных людей.
- Груды прилагательных вроде «masterpiece, best quality, 8k, ultra detailed» — на современных моделях это шум, а не буст. Работают конкретные существительные.
- Отрицания внутри основного промпта («без текста») — для этого есть `negative_prompt` там, где он поддерживается.

## Согласованность серии

Чтобы несколько картинок выглядели как один набор:

1. Зафиксируй `seed` и меняй только сюжетную часть промпта.
2. Держи неизменным хвост промпта — свет, оптику, палитру.
3. Ещё надёжнее: сгенерируй одну эталонную, а остальные делай через edit-модель по ней как по референсу — так держится не только настроение, но и фактура.
