# Media Processor (and downloader and uploader)

## Input

It fetches its work from two sources: a directory and the system clipboard.

## Supported clipboard formats

* YT urls. (processing via yt_dlp python module)

## Supported file formats

* ZIP files with one (not two or more) .html files get their html file extracted and fed to TTS. (process: ZIP -> ZIP+HTML+AUDIO) The purpose of this is to act as a processor for Google Documents -> "Download as Web Page (.html, zipped)" to provide an easy way to get your Google docs onto your phone where you can have your phone's TTS read the html or listen to the already generated AUDIO directly (Google's TTS doesn't work for too short texts...).

## Audio Post-Processing

* Largely unnecessary. Websites like YT do loudness normalization already (AFAIK) and mono conversion tends to happen on your phone if you plug in only one earbud.

## Upload

* FTP (likely unencrypted) - WiFi FTP Server is a good Android app
* SCP (SSH) - use a password-less SSH key - I'm using it with termux sshd on Android
* move to (local) folder

## TODO

* Support more URLs?
* Support running custom commands for upload/processing?
* timeouts/batchmode


--
git@nas:py.git@0db2111bb0745fd7150ce271360ef9df59614468
