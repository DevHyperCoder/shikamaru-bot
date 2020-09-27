import hikari
import lightbulb
import re
import zlib
import io
import os
import aiohttp
from ..utils import fuzzy
from datetime import datetime


class SphinxObjectFileReader:
    # Inspired by Sphinx's InventoryFileReader
    BUFSIZE = 16 * 1024

    def __init__(self, buffer):
        self.stream = io.BytesIO(buffer)

    def readline(self):
        return self.stream.readline().decode('utf-8')

    def skipline(self):
        self.stream.readline()

    def read_compressed_chunks(self):
        decompressor = zlib.decompressobj()
        while True:
            chunk = self.stream.read(self.BUFSIZE)
            if len(chunk) == 0:
                break
            yield decompressor.decompress(chunk)
        yield decompressor.flush()

    def read_compressed_lines(self):
        buf = b''
        for chunk in self.read_compressed_chunks():
            buf += chunk
            pos = buf.find(b'\n')
            while pos != -1:
                yield buf[:pos].decode('utf-8')
                buf = buf[pos + 1:]
                pos = buf.find(b'\n')


class RTFM(lightbulb.Plugin):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.docs_links = {'dpy':'https://discordpy.readthedocs.io/en/latest/', 'discord.py':'https://discordpy.readthedocs.io/en/latest/', 'lightbulb': 'https://tandemdude.gitlab.io/lightbulb/', 'zenora': 'https://zenora-py.github.io', 'asyncio': 'https://asyncio.readthedocs.io/en/latest/', }

    def parse_object_inv(self, stream, url):
        # key: URL
        result = {}

        # first line is version info
        inv_version = stream.readline().rstrip()

        if inv_version != '# Sphinx inventory version 2':
            raise RuntimeError('Invalid objects.inv file version.')

        # next line is "# Project: <name>"
        # then after that is "# Version: <version>"
        projname = stream.readline().rstrip()[11:]
        version = stream.readline().rstrip()[11:]

        # next line says if it's a zlib header
        line = stream.readline()
        if 'zlib' not in line:
            raise RuntimeError(
                'Invalid objects.inv file, not z-lib compatible.')

        # This code mostly comes from the Sphinx repository.
        entry_regex = re.compile(
            r'(?x)(.+?)\s+(\S*:\S*)\s+(-?\d+)\s+(\S+)\s+(.*)')
        for line in stream.read_compressed_lines():
            match = entry_regex.match(line.rstrip())
            if not match:
                continue

            name, directive, prio, location, dispname = match.groups()
            domain, _, subdirective = directive.partition(':')
            if directive == 'py:module' and name in result:
                # From the Sphinx Repository:
                # due to a bug in 1.1 and below,
                # two inventory entries are created
                # for Python modules, and the first
                # one is correct
                continue

            # Most documentation pages have a label
            if directive == 'std:doc':
                subdirective = 'label'

            if location.endswith('$'):
                location = location[:-1] + name

            key = name if dispname == '-' else dispname
            prefix = f'{subdirective}:' if domain == 'std' else ''

            to_remove = ["lawf.", "errors.", "serving.",
                         "request.", "response.", "server.", "filetypes."]
            for s in to_remove:
                key = key.replace(s, "")

            result[f'{prefix}{key}'] = os.path.join(url, location)

        return result

    async def build_rtfm_lookup_table(self, page_types):
        cache = {}
        for key, page in page_types.items():
            sub = cache[key] = {}
            async with aiohttp.ClientSession() as session:
                async with session.get(page + '/objects.inv') as resp:
                    if resp.status != 200:
                        raise RuntimeError(
                            'Cannot build rtfm lookup table, try again later.')

                    stream = SphinxObjectFileReader(await resp.read())
                    cache[key] = self.parse_object_inv(stream, page)

        self._rtfm_cache = cache

    async def do_rtfm(self, ctx, site, key, obj):
        if not site in self.docs_links:
            await ctx.reply("RTFM not available for " + str(site) + ".")
            return
        print(self.docs_links[site])
        page_types = {
            'latest': self.docs_links[site],
        }

        if obj is None:
            await ctx.send(page_types[key])
            return

        if not hasattr(self, '_rtfm_cache'):
            #await ctx.trigger_typing()
            await self.build_rtfm_lookup_table(page_types)

        cache = list(self._rtfm_cache[key].items())

        def transform(tup):
            return tup[0]

        matches = fuzzy.finder(obj, cache, key=lambda t: t[0], lazy=False)[:8]

        e = hikari.Embed(
                          title=f"Reading the docs are a drag...")
        if len(matches) == 0:
            return await ctx.reply('Could not find anything. Sorry.')
        e.timestamp = datetime.utcnow()
        e.description = '\n'.join(f'[`{key}`]({url})' for key, url in matches)
        await ctx.reply(embed=e)

    @lightbulb.command()
    async def rtfm(self, ctx, module, *, obj: str = None):
        """Gives you a documentation link for an entity."""
        key = 'latest'
        await self.do_rtfm(ctx, module, key, obj)


def load(bot):
    bot.add_plugin(RTFM(bot))