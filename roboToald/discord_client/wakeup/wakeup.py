import asyncio

import disnake

from roboToald import config


async def process_message(message: disnake.Message) -> None:
    channel_id = message.channel.id
    if channel_id in config.WAKEUP_CHANNELS and message.mention_everyone:
        for exclusion in config.get_wakeup_exclusions(message.guild.id):
            if exclusion in message.content.lower():
                return
        print(f"Playing wakeup in channel {channel_id} for message: "
              f"{message.content}")
        voice_channel_id = config.WAKEUP_CHANNELS[channel_id]
        voice_channel = message.guild.get_channel(voice_channel_id)
        try:
            await wakeup(voice_channel)
        except disnake.errors.ClientException:
            print("Already connected to a voice channel, likely a duplicate trigger.")
        except Exception as e:
            print(f"Unexpected error during wakeup: {e}")


async def wakeup(channel: disnake.VoiceChannel) -> None:
    vc: disnake.voice_client.VoiceClient = await channel.connect()
    try:
        def finished(error):
            if error:
                print(error)

        wakeup_sound = disnake.FFmpegPCMAudio(config.WAKEUP_AUDIOFILE)
        vc.play(wakeup_sound, after=finished)
        timeout = 60
        elapsed = 0
        while vc.is_playing() and elapsed < timeout:
            await asyncio.sleep(1)
            elapsed += 1
        if elapsed >= timeout:
            print(f"Wakeup playback timed out after {timeout}s, forcing disconnect")
            vc.stop()
    except Exception as e:
        print(f"Wakeup voice error: {e}")
    finally:
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
