#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
    CLI Interface for ytresolver
"""
import argparse
import json
import os
import sys

from .kodion.context.standalone import StandaloneContext
from .youtube.client.player_client import YouTubePlayerClient
from .youtube.helper.url_resolver import UrlResolver


def main():
    parser = argparse.ArgumentParser(prog="ytresolver", description="YouTube Stream Resolver CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    resolve_parser = subparsers.add_parser("resolve", help="Resolve YouTube video/playlist URL or ID")
    resolve_parser.add_argument("target", help="YouTube Video ID, Playlist ID, or URL")
    resolve_parser.add_argument("--json", action="store_true", help="Output result as formatted JSON")

    search_parser = subparsers.add_parser("search", help="Search YouTube for videos")
    search_parser.add_argument("query", help="Search query string")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    context = StandaloneContext(
        data_dir=os.path.abspath("data"),
        config_file=os.path.abspath("config.json")
    )
    client = YouTubePlayerClient(context=context)

    if args.command == "resolve":
        target = args.target
        video_id = target
        if target.startswith("http://") or target.startswith("https://"):
            resolver = UrlResolver(context)
            resolved_url = resolver.resolve(target)
            from .kodion.compatibility import parse_qs, urlsplit
            qs = parse_qs(urlsplit(resolved_url).query)
            video_id = qs.get("v", [target])[0]

        try:
            streams, yt_item = client.load_stream_info(video_id=video_id, use_mpd=True)
            result = {
                "video_id": video_id,
                "title": yt_item.get_name() if yt_item else "",
                "streams": streams
            }
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"Title: {result['title']}")
                print(f"Video ID: {result['video_id']}")
                print(f"Available Streams: {len(streams)}")
                for idx, stream in enumerate(streams[:5]):
                    print(f"  [{idx+1}] {stream.get('title', 'N/A')} - {stream.get('container', '')} ({stream.get('url', '')[:80]}...)")
        except Exception as e:
            print(f"Error resolving {target}: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "search":
        try:
            _, json_data = client.search_with_params(params={"q": args.query, "type": "video"})
            print(json.dumps(json_data or {}, indent=2))
        except Exception as e:
            print(f"Error searching {args.query}: {e}", file=sys.stderr)
            sys.exit(1)

    context.tear_down()


if __name__ == '__main__':
    main()
