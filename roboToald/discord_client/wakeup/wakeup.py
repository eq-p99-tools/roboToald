import asyncio
import logging

import disnake

from roboToald import config

logging.getLogger("disnake.voice_client").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def process_message(message: disnake.Message) -> None:
    channel_id = message.channel.id
    if channel_id in config.WAKEUP_CHANNELS and message.mention_everyone:
        for exclusion in config.get_wakeup_exclusions(message.guild.id):
            if exclusion in message.content.lower():
                return
        logger.info("Playing wakeup in channel %s for message: %s", channel_id, message.content)
        voice_channel_id = config.WAKEUP_CHANNELS[channel_id]
        voice_channel = message.guild.get_channel(voice_channel_id)
        try:
            await wakeup(voice_channel)
        except disnake.errors.ClientException:
            logger.warning("Already connected to a voice channel, likely a duplicate trigger.")
        except Exception:
            logger.exception("Unexpected error during wakeup")


async def wakeup(channel: disnake.VoiceChannel) -> None:
    vc: disnake.voice_client.VoiceClient = await channel.connect()
    try:
        for _ in range(10):
            if vc.is_connected():
                break
            await asyncio.sleep(0.5)
        if not vc.is_connected():
            logger.warning("Voice connection failed: not connected after waiting")
            return

        def finished(error):
            if error:
                logger.warning("Wakeup playback finished with error: %s", error)

        wakeup_sound = disnake.FFmpegPCMAudio(config.WAKEUP_AUDIOFILE)
        vc.play(wakeup_sound, after=finished)
        timeout = 60
        elapsed = 0
        while vc.is_playing() and elapsed < timeout:
            await asyncio.sleep(1)
            elapsed += 1
        if elapsed >= timeout:
            logger.warning("Wakeup playback timed out after %ss, forcing disconnect", timeout)
            vc.stop()
    except Exception:
        logger.exception("Wakeup voice error")
    finally:
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
