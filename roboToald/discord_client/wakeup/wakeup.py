import asyncio

import disnake

from roboToald import config


async def process_message(message: disnake.Message) -> None:
    channel_id = message.channel.id
    if channel_id in config.WAKEUP_CHANNELS and message.mention_everyone:
        print(f"Playing wakeup in channel {channel_id} for message: "
              f"{message.content}")
        voice_channel_id = config.WAKEUP_CHANNELS[channel_id]
        voice_channel = message.guild.get_channel(voice_channel_id)
        await wakeup(voice_channel)


async def wakeup(channel: disnake.VoiceChannel) -> None:
    vc: disnake.voice_client.VoiceClient = await channel.connect()

    def finished(error):
        if error:
            print(error)

    wakeup_sound = disnake.FFmpegPCMAudio(config.WAKEUP_AUDIOFILE)
    vc.play(wakeup_sound, after=finished)
    while vc.is_playing():
        await asyncio.sleep(1)
    await vc.disconnect()
