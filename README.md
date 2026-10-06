# RandomPick Bot Update Log

## v0.1.0

* Added `picknumber`, `pickfloat`, `testpercent`, and `dice`

## v0.2.0

* Added `pickword`
* Removed `dice`

## v1.0.0

* Added `randompic`
* Updated from a Discord bot to an app

## v1.1.0

* Added `randomgif`

## v1.1.1

* Significantly expanded the image range for `randompic`
* Significantly expanded the GIF range for `randomgif`

## v1.2.0

* Added `wordquiz`

## v1.3.0

* Added HELL difficulty to `wordquiz`

## v1.4.0

* Removed the multi-tag feature from `randompic`
* Banned certain tags in `randompic`

## v1.4.1

* Security update (removed internal vulnerabilities)

## v1.5.0

* Added `randomemoji` and `faq`

## v1.5.1

* Fixed a bug where GIFs failed to load in `randomgif`
* Fixed a bug where text was outputted instead of emojis in `randomemoji`

## v1.5.2

* Security update (fixed API key exposure bug)

## v1.6.0

* Added Info, View, and Source buttons to `randompic`

## v1.6.1

* Security update
* Fixed a bug where images were displayed twice in `randompic`

## v1.6.2

* Fixed a bug where buttons disappeared in `randompic`

## v1.7.0

* Added a `OneMore` button to `randompic`

## v1.7.1

* Restored servers for `randompic` and multiple services
* Optimization

## v1.8.0

* Stabilized `randompic` (fixed a bug where responses occasionally dropped)
* Fixed soft-lock bugs
* Updated `randompic` so that hints can now be received when there are no tags

## v1.9.0

* Updated `randompic` so that the `info` and `onemore` buttons work even after the bot restarts (only works from this version onwards)
* Revamped the `randompic` `info` button to be more informative
* Added the image ID display at the bottom of `randompic`
* Display the bot's recent startup time as its status message

## v2.0.0

* Removed all commands except `randompic`, `randomemoji`, and `faq`
* Revised `randompic` tag hints
* Added `randompic` tag auto-completion
* Added a cooldown for `randompic`
* Display user nicknames when using `randompic` (including `OneMore`)
* Results for non-existent `randompic` items are now only visible to the user
* Immediate execution via recommended tags now available for non-existent `randompic` results
* Added a delete feature in `randompic` (available only to the user)
* Added a bookmark feature in `randompic`
* Optimization
* Security update (fixed user ID exposure bug)

## v2.0.1

* Fixed a bug where the bot did not work on certain servers

## v2.0.2

* Fixed a bug where some features were rolled back

## v2.1.0

* Removed features in `randompic` that were only visible to the user (due to Discord system limitations)
* Revived multi-tags for `randompic`
* Relaxed image limits for `randompic`

## v2.1.1

* Updated `randompic` to recognize commas (`,`) as spaces
* Fixed a bug where markdown syntax was applied to tags in `randompic`
* Added entries to `faq`

## v2.2.0

* Added a community server link for `randompick` to `faq` and the description area

## v2.3.0

* Added the `setting` command
* Added the ability to configure AI illustration display settings for `randompic` via `setting`
## v2.3.1

* Fixed a bug with default settings
## v2.3.2

* Blocked `rating:questionable`
