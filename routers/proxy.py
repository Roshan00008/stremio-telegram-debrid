import asyncio
import logging
import zipfile
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response, StreamingResponse
from auth import check_api_key
from config import Config
from services.channels import assert_channel_allowed
from tg_client import tg_client_manager
from zip_helper import (
    TelegramSeekableReader,
    get_zip_entry_data_offset,
    list_zip_files,
    zip_compressed_generator,
)

logger = logging.getLogger("stremio_addon")
router = APIRouter(tags=["proxy"])


def _parse_range(range_header, file_size):
    start, end = 0, file_size - 1
    if range_header:
        try:
            bytes_range = range_header.replace("bytes=", "").split("-")
            if bytes_range[0]:
                start = int(bytes_range[0])
            if len(bytes_range) > 1 and bytes_range[1]:
                end = int(bytes_range[1])
        except ValueError:
            pass
    return start, end


def _require_api_key(api_key: str, request: Request):
    check_api_key(api_key, request.query_params.get("api_key", ""))


def _parse_chat_id(chat_id: str):
    try:
        return int(chat_id)
    except ValueError:
        return chat_id


def _require_channel(chat_id: str, request: Request):
    assert_channel_allowed(_parse_chat_id(chat_id), request)

@router.api_route("/stream/subtitle/{chat_id}/{message_id}/{filename}", methods=["GET", "HEAD"])
async def tg_subtitle_proxy(
    chat_id: str, 
    message_id: int, 
    filename: str,
    request: Request,
    api_key: str = ""
):
    _require_api_key(api_key, request)
    _require_channel(chat_id, request)

    try:
        chat_id_val = _parse_chat_id(chat_id)
        msg = await tg_client_manager.get_message(message_id, chat_id=chat_id_val)
    except Exception as e:
        logger.error(f"Proxy failed to fetch subtitle message: {e}")
        raise HTTPException(status_code=404, detail="Subtitle file not found")
        
    if not msg:
        raise HTTPException(status_code=404, detail="Subtitle message not found")
        
    media = msg.document or msg.audio or msg.video
    if not media:
        raise HTTPException(status_code=404, detail="No media found in subtitle message")
        
    content_type = "text/plain"
    filename_lower = filename.lower()
    if filename_lower.endswith(".srt"):
        content_type = "application/x-subrip"
    elif filename_lower.endswith(".vtt"):
        content_type = "text/vtt"
    elif filename_lower.endswith(".ass"):
        content_type = "text/plain"
        
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Access-Control-Allow-Origin": "*",
        "Content-Length": str(media.file_size),
    }
    
    if request.method == "HEAD":
        return Response(
            status_code=200,
            media_type=content_type,
            headers=headers
        )
        
    try:
        logger.info(f"Downloading subtitle file from Telegram: {filename} (msg ID {message_id})")
        file_buffer = await tg_client_manager.client.download_media(msg, in_memory=True)
        content = file_buffer.getvalue()
    except Exception as e:
        logger.error(f"Failed to download subtitle file: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve subtitle media")
        
    return Response(
        content=content,
        media_type=content_type,
        headers=headers
    )

@router.api_route("/stream/file/{chat_id}/{message_id}/{filename}", methods=["GET", "HEAD"])
async def tg_stream_proxy(
    chat_id: str, 
    message_id: int, 
    filename: str, 
    request: Request,
    api_key: str = ""
):
    _require_api_key(api_key, request)
    _require_channel(chat_id, request)

    try:
        chat_id_val = _parse_chat_id(chat_id)
        msg = await tg_client_manager.get_message(message_id, chat_id=chat_id_val)
    except Exception as e:
        logger.error(f"Proxy failed to fetch message: {e}")
        raise HTTPException(status_code=404, detail="Media file not found")
        
    if not msg:
        raise HTTPException(status_code=404, detail="Media message not found")
        
    media = msg.video or msg.document or msg.audio
    if not media:
        raise HTTPException(status_code=404, detail="No playable media found in message")
        
    file_size = media.file_size
    mime_type = media.mime_type or "video/mp4"
    
    if request.method == "GET":
        asyncio.create_task(
            tg_client_manager.send_play_log(filename, chat_id_val, message_id)
        )
    
    range_header = request.headers.get("Range")
    start = 0
    end = file_size - 1
    
    if range_header:
        try:
            bytes_range = range_header.replace("bytes=", "").split("-")
            if bytes_range[0]:
                start = int(bytes_range[0])
            if len(bytes_range) > 1 and bytes_range[1]:
                end = int(bytes_range[1])
        except ValueError:
            pass
            
    content_length = end - start + 1
    
    chunk_size = 1024 * 1024
    offset = start // chunk_size
    skip_bytes = start % chunk_size
    
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Disposition": f'inline; filename="{filename}"',
    }
    
    status_code = 206 if range_header else 200
    
    if request.method == "HEAD":
        logger.info(f"HEAD request for media '{filename}' (bytes {start}-{end}/{file_size}) - Status {status_code}")
        return Response(
            status_code=status_code,
            media_type=mime_type,
            headers=headers
        )
        
    async def file_generator():
        bytes_sent = 0
        bytes_to_skip = skip_bytes
        try:
            async for chunk in tg_client_manager.client.stream_media(media, offset=offset):
                if bytes_to_skip > 0:
                    if bytes_to_skip < len(chunk):
                        chunk = chunk[bytes_to_skip:]
                        bytes_to_skip = 0
                    else:
                        bytes_to_skip -= len(chunk)
                        continue
                        
                if bytes_sent + len(chunk) > content_length:
                    chunk = chunk[:content_length - bytes_sent]
                    
                yield chunk
                bytes_sent += len(chunk)
                
                if bytes_sent >= content_length:
                    break
        except Exception as e:
            logger.error(f"Streaming error on message {message_id}: {e}")
            
    logger.info(f"Streaming media '{filename}' (bytes {start}-{end}/{file_size}) - Status {status_code}")
    
    return StreamingResponse(
        file_generator(),
        status_code=status_code,
        media_type=mime_type,
        headers=headers
    )

@router.api_route("/stream/split/{chat_id}/{message_ids}/{filename}", methods=["GET", "HEAD"])
async def tg_split_stream_proxy(
    chat_id: str, 
    message_ids: str, 
    filename: str, 
    request: Request,
    api_key: str = ""
):
    _require_api_key(api_key, request)
    _require_channel(chat_id, request)

    msg_id_list = [int(x) for x in message_ids.split(",") if x.strip().isdigit()]
    if not msg_id_list:
        raise HTTPException(status_code=400, detail="Invalid message IDs")

    chat_id_val = _parse_chat_id(chat_id)
        
    if request.method == "GET":
        asyncio.create_task(
            tg_client_manager.send_play_log(filename, chat_id_val, msg_id_list[0])
        )
        
    chunks_info = []
    total_size = 0
    try:
        messages = await tg_client_manager.get_messages_batch(msg_id_list, chat_id=chat_id_val)
        if len(messages) != len(msg_id_list):
            raise HTTPException(status_code=404, detail="One or more split messages not found")
        for msg in messages:
            media = msg.video or msg.document or msg.audio
            if not media:
                raise HTTPException(status_code=400, detail=f"No media in message {msg.id}")
            chunks_info.append({
                "media": media,
                "size": media.file_size,
                "start_byte": total_size,
                "end_byte": total_size + media.file_size - 1,
            })
            total_size += media.file_size
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching split metadata: {e}")
        raise HTTPException(status_code=500, detail="Failed resolving split file metadata")
            
    range_header = request.headers.get("Range")
    start = 0
    end = total_size - 1
    
    if range_header:
        try:
            bytes_range = range_header.replace("bytes=", "").split("-")
            if bytes_range[0]:
                start = int(bytes_range[0])
            if len(bytes_range) > 1 and bytes_range[1]:
                end = int(bytes_range[1])
        except ValueError:
            pass
            
    content_length = end - start + 1
    mime_type = chunks_info[0]["media"].mime_type or "video/mp4"
    
    headers = {
        "Content-Range": f"bytes {start}-{end}/{total_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Disposition": f'inline; filename="{filename}"',
    }
    
    status_code = 206 if range_header else 200
    
    if request.method == "HEAD":
        return Response(
            status_code=status_code,
            media_type=mime_type,
            headers=headers
        )
        
    async def split_file_generator():
        bytes_sent = 0
        block_size = 1024 * 1024  # 1 MB blocks
        
        for chunk in chunks_info:
            c_start = chunk["start_byte"]
            c_end = chunk["end_byte"]
            
            if c_end < start or c_start > end:
                continue
                
            read_start = max(c_start, start)
            read_end = min(c_end, end)
            chunk_read_len = read_end - read_start + 1
            
            local_offset = read_start - c_start
            offset_blocks = local_offset // block_size
            skip_bytes = local_offset % block_size
            
            chunk_bytes_sent = 0
            bytes_to_skip = skip_bytes
            
            try:
                async for block in tg_client_manager.client.stream_media(chunk["media"], offset=offset_blocks):
                    if bytes_to_skip > 0:
                        if bytes_to_skip < len(block):
                            block = block[bytes_to_skip:]
                            bytes_to_skip = 0
                        else:
                            bytes_to_skip -= len(block)
                            continue
                            
                    if chunk_bytes_sent + len(block) > chunk_read_len:
                        block = block[:chunk_read_len - chunk_bytes_sent]
                        
                    yield block
                    chunk_bytes_sent += len(block)
                    bytes_sent += len(block)
                    
                    if chunk_bytes_sent >= chunk_read_len:
                        break
            except Exception as e:
                logger.error(f"Error streaming split chunk: {e}")
                break
                
            if bytes_sent >= content_length:
                break
                
    logger.info(f"Streaming split media '{filename}' (bytes {start}-{end}/{total_size}) - Status {status_code}")
    
    return StreamingResponse(
        split_file_generator(),
        status_code=status_code,
        media_type=mime_type,
        headers=headers
    )

@router.api_route("/stream/zip/{chat_id}/{message_ids}/{filename}", methods=["GET", "HEAD"])
async def tg_zip_stream_proxy(
    chat_id: str,
    message_ids: str,
    filename: str,
    request: Request,
    api_key: str = ""
):
    _require_api_key(api_key, request)
    _require_channel(chat_id, request)

    msg_id_list = [int(x) for x in message_ids.split(",") if x.strip().isdigit()]
    if not msg_id_list:
        raise HTTPException(status_code=400, detail="Invalid message IDs")

    chat_id_val = _parse_chat_id(chat_id)
        
    if request.method == "GET":
        asyncio.create_task(
            tg_client_manager.send_play_log(filename, chat_id_val, msg_id_list[0])
        )
        
    messages = await tg_client_manager.get_messages_batch(msg_id_list, chat_id=chat_id_val)
    if not messages:
        raise HTTPException(status_code=404, detail="Messages not found")
        
    zip_entries = await list_zip_files(tg_client_manager.client, messages)
    target_entry = None
    for entry in zip_entries:
        if entry.filename == filename:
            target_entry = entry
            break
            
    if not target_entry:
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found in ZIP archive")
        
    file_size = target_entry.file_size
    mime_type = "video/mp4"
    filename_lower = filename.lower()
    if filename_lower.endswith(".mkv"):
        mime_type = "video/x-matroska"
    elif filename_lower.endswith(".mp4"):
        mime_type = "video/mp4"
    elif filename_lower.endswith(".avi"):
        mime_type = "video/x-msvideo"
        
    range_header = request.headers.get("Range")
    start = 0
    end = file_size - 1
    
    if range_header:
        try:
            bytes_range = range_header.replace("bytes=", "").split("-")
            if bytes_range[0]:
                start = int(bytes_range[0])
            if len(bytes_range) > 1 and bytes_range[1]:
                end = int(bytes_range[1])
        except ValueError:
            pass
            
    content_length = end - start + 1
    
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Disposition": f'inline; filename="{filename}"',
    }
    
    status_code = 206 if range_header else 200
    
    if request.method == "HEAD":
        return Response(
            status_code=status_code,
            media_type=mime_type,
            headers=headers
        )
        
    if target_entry.compress_type == zipfile.ZIP_STORED:
        logger.info(f"ZIP entry '{filename}' is STORED (uncompressed). Using direct offset proxy.")
        reader = TelegramSeekableReader(tg_client_manager.client, messages)
        data_start = await get_zip_entry_data_offset(reader, target_entry.header_offset)
        
        stream_start = data_start + start
        stream_end = data_start + end
        stream_len = stream_end - stream_start + 1
        
        chunks_info = []
        total_size = 0
        
        for part in reader.parts:
            chunks_info.append({
                "media": part["media"],
                "size": part["size"],
                "start_byte": part["start"],
                "end_byte": part["end"] - 1
            })
            total_size += part["size"]
            
        async def split_file_generator():
            bytes_sent = 0
            block_size = 1024 * 1024
            
            for chunk in chunks_info:
                c_start = chunk["start_byte"]
                c_end = chunk["end_byte"]
                
                if c_end < stream_start or c_start > stream_end:
                    continue
                    
                read_start = max(c_start, stream_start)
                read_end = min(c_end, stream_end)
                chunk_read_len = read_end - read_start + 1
                
                local_offset = read_start - c_start
                offset_blocks = local_offset // block_size
                skip_bytes = local_offset % block_size
                
                chunk_bytes_sent = 0
                bytes_to_skip = skip_bytes
                
                try:
                    async for block in tg_client_manager.client.stream_media(chunk["media"], offset=offset_blocks):
                        if bytes_to_skip > 0:
                            if bytes_to_skip < len(block):
                                block = block[bytes_to_skip:]
                                bytes_to_skip = 0
                            else:
                                bytes_to_skip -= len(block)
                                continue
                                
                        if chunk_bytes_sent + len(block) > chunk_read_len:
                            block = block[:chunk_read_len - chunk_bytes_sent]
                            
                        yield block
                        chunk_bytes_sent += len(block)
                        bytes_sent += len(block)
                        
                        if chunk_bytes_sent >= chunk_read_len:
                            break
                except Exception as e:
                    logger.error(f"Error streaming split ZIP chunk: {e}")
                    break
                    
                if bytes_sent >= stream_len:
                    break
                    
        logger.info(f"Streaming uncompressed ZIP entry '{filename}' (raw bytes {stream_start}-{stream_end}/{total_size}) - Status {status_code}")
        return StreamingResponse(
            split_file_generator(),
            status_code=status_code,
            media_type=mime_type,
            headers=headers
        )
    else:
        logger.info(f"ZIP entry '{filename}' is COMPRESSED (type {target_entry.compress_type}). Streaming on-the-fly decompression.")
        reader = TelegramSeekableReader(tg_client_manager.client, messages)
        return StreamingResponse(
            zip_compressed_generator(reader, filename, start, end),
            status_code=status_code,
            media_type=mime_type,
            headers=headers
        )
