import os
import uuid
import shutil
import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
import imageio_ffmpeg

from bson import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING
from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
VIDEO_DIR = UPLOAD_DIR / "videos"
AVATAR_DIR = UPLOAD_DIR / "avatars"
THUMBNAIL_DIR = UPLOAD_DIR / "thumbnails"

for directory in [UPLOAD_DIR, VIDEO_DIR, AVATAR_DIR, THUMBNAIL_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

MONGODB_URI = os.getenv("MONGODB_URI", "")
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
PORT = int(os.getenv("PORT", "10000"))

if not MONGODB_URI:
    print("WARNING: MONGODB_URI is not configured.")

client = None
db = None

if MONGODB_URI:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client["isrtube"]

    users_collection = db["users"]
    videos_collection = db["videos"]
    comments_collection = db["comments"]
    likes_collection = db["likes"]

    try:
        users_collection.create_index("username", unique=True)
        users_collection.create_index("email", unique=True)
        videos_collection.create_index([("createdAt", DESCENDING)])
        videos_collection.create_index([("title", ASCENDING)])
        comments_collection.create_index([("videoId", ASCENDING)])
        likes_collection.create_index(
            [("videoId", ASCENDING), ("userId", ASCENDING)],
            unique=True,
        )
    except Exception as e:
        print("MongoDB index warning:", e)


# ============================================================
# APP
# ============================================================

app = FastAPI(title="IsrTube")

app.mount(
    "/uploads",
    StaticFiles(directory=str(UPLOAD_DIR)),
    name="uploads",
)


# ============================================================
# HELPERS
# ============================================================

def require_db():
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="MongoDB is not configured.",
        )


def serialize_id(value):
    return str(value) if isinstance(value, ObjectId) else value


def serialize_user(user):
    return {
        "id": serialize_id(user["_id"]),
        "username": user["username"],
        "email": user.get("email", ""),
        "avatar": user.get("avatar", ""),
        "createdAt": user.get("createdAt"),
    }


def serialize_video(video):
    return {
        "id": serialize_id(video["_id"]),
        "title": video.get("title", ""),
        "description": video.get("description", ""),
        "videoUrl": video.get("videoUrl", ""),
        "thumbnailUrl": video.get("thumbnailUrl", ""),
        "ownerId": serialize_id(video["ownerId"]),
        "ownerUsername": video.get("ownerUsername", ""),
        "ownerAvatar": video.get("ownerAvatar", ""),
        "views": video.get("views", 0),
        "likes": video.get("likes", 0),
        "duration": video.get("duration", 0),
        "createdAt": video.get("createdAt"),
    }


def create_token(user_id):
    payload = {
        "userId": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm="HS256",
    )


def get_current_user(request: Request):
    require_db()

    auth = request.headers.get("Authorization", "")

    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    token = auth.replace("Bearer ", "", 1)

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
        )

        user_id = ObjectId(payload["userId"])

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token.",
        )

    user = users_collection.find_one({"_id": user_id})

    if not user:
        raise HTTPException(
            status_code=401,
            detail="User not found.",
        )

    return user


def get_optional_user(request: Request):
    try:
        return get_current_user(request)
    except HTTPException:
        return None


# ============================================================
# WEBSOCKET MANAGER
# ============================================================

class ConnectionManager:
    def __init__(self):
        self.connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, data):
        disconnected = []

        for connection in self.connections:
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket)

    except Exception:
        manager.disconnect(websocket)


# ============================================================
# AUTH
# ============================================================

@app.post("/api/register")
async def register(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    require_db()

    username = username.strip()
    email = email.strip().lower()

    if len(username) < 3:
        raise HTTPException(
            status_code=400,
            detail="Username must contain at least 3 characters.",
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 6 characters.",
        )

    if users_collection.find_one(
        {
            "$or": [
                {"username": username},
                {"email": email},
            ]
        }
    ):
        raise HTTPException(
            status_code=400,
            detail="Username or email already exists.",
        )

    password_hash = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    user = {
        "username": username,
        "email": email,
        "passwordHash": password_hash,
        "avatar": "",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    result = users_collection.insert_one(user)

    token = create_token(result.inserted_id)

    return {
        "token": token,
        "user": serialize_user(
            users_collection.find_one({"_id": result.inserted_id})
        ),
    }


@app.post("/api/login")
async def login(
    email: str = Form(...),
    password: str = Form(...),
):
    require_db()

    email = email.strip().lower()

    user = users_collection.find_one(
        {"email": email}
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    valid = bcrypt.checkpw(
        password.encode("utf-8"),
        user["passwordHash"].encode("utf-8"),
    )

    if not valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    return {
        "token": create_token(user["_id"]),
        "user": serialize_user(user),
    }


@app.get("/api/me")
async def me(request: Request):
    user = get_current_user(request)

    return {
        "user": serialize_user(user)
    }


# ============================================================
# AVATAR
# ============================================================

@app.post("/api/avatar")
async def upload_avatar(
    request: Request,
    avatar: UploadFile = File(...),
):
    user = get_current_user(request)

    allowed = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    if avatar.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG and WebP images are allowed.",
        )

    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[avatar.content_type]

    filename = f"{uuid.uuid4().hex}{extension}"
    filepath = AVATAR_DIR / filename

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(avatar.file, buffer)

    avatar_url = f"/uploads/avatars/{filename}"

    users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"avatar": avatar_url}},
    )

    return {
        "avatar": avatar_url
    }


# ============================================================
# VIDEO COMPRESSION
# ============================================================

def compress_video(input_path: Path, output_path: Path):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),

        # Video
        "-c:v",
        "libx264",

        # Compression
        "-preset",
        "medium",
        "-crf",
        "27",

        # Maximum reasonable resolution
        "-vf",
        "scale='min(1280,iw)':-2",

        # Audio
        "-c:a",
        "aac",
        "-b:a",
        "128k",

        # Web-friendly MP4
        "-movflags",
        "+faststart",

        str(output_path),
    ]

    subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


# ============================================================
# VIDEO UPLOAD
# ============================================================

@app.post("/api/videos")
async def upload_video(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    video: UploadFile = File(...),
):
    user = get_current_user(request)

    if not video.content_type:
        raise HTTPException(
            status_code=400,
            detail="Invalid video.",
        )

    if not video.content_type.startswith("video/"):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a video.",
        )

    temporary_name = f"{uuid.uuid4().hex}_source"
    extension = Path(video.filename or ".mp4").suffix or ".mp4"

    source_path = VIDEO_DIR / f"{temporary_name}{extension}"
    final_filename = f"{uuid.uuid4().hex}.mp4"
    final_path = VIDEO_DIR / final_filename

    try:
        with open(source_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)

        # Run compression in a worker thread so the API stays responsive.
        await asyncio.to_thread(
            compress_video,
            source_path,
            final_path,
        )

    except subprocess.CalledProcessError:
        raise HTTPException(
            status_code=500,
            detail="Video compression failed.",
        )

    finally:
        if source_path.exists():
            source_path.unlink()

    video_url = f"/uploads/videos/{final_filename}"

    document = {
        "title": title.strip(),
        "description": description.strip(),
        "videoUrl": video_url,
        "thumbnailUrl": "",
        "ownerId": user["_id"],
        "ownerUsername": user["username"],
        "ownerAvatar": user.get("avatar", ""),
        "views": 0,
        "likes": 0,
        "duration": 0,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    result = videos_collection.insert_one(document)

    created = videos_collection.find_one(
        {"_id": result.inserted_id}
    )

    await manager.broadcast(
        {
            "type": "new_video",
            "video": serialize_video(created),
        }
    )

    return {
        "video": serialize_video(created)
    }


# ============================================================
# VIDEOS
# ============================================================

@app.get("/api/videos")
async def get_videos(
    request: Request,
    search: str = "",
):
    require_db()

    query = {}

    if search.strip():
        query = {
            "$or": [
                {
                    "title": {
                        "$regex": search.strip(),
                        "$options": "i",
                    }
                },
                {
                    "ownerUsername": {
                        "$regex": search.strip(),
                        "$options": "i",
                    }
                },
            ]
        }

    videos = list(
        videos_collection
        .find(query)
        .sort("createdAt", DESCENDING)
        .limit(100)
    )

    return {
        "videos": [
            serialize_video(video)
            for video in videos
        ]
    }


@app.get("/api/videos/{video_id}")
async def get_video(
    video_id: str,
    request: Request,
):
    require_db()

    try:
        object_id = ObjectId(video_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid video ID.",
        )

    video = videos_collection.find_one(
        {"_id": object_id}
    )

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    return {
        "video": serialize_video(video)
    }


@app.post("/api/videos/{video_id}/view")
async def add_view(
    video_id: str,
):
    require_db()

    try:
        object_id = ObjectId(video_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid video ID.",
        )

    result = videos_collection.find_one_and_update(
        {"_id": object_id},
        {"$inc": {"views": 1}},
        return_document=True,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    return {
        "views": result.get("views", 0)
    }


# ============================================================
# LIKES
# ============================================================

@app.post("/api/videos/{video_id}/like")
async def toggle_like(
    video_id: str,
    request: Request,
):
    user = get_current_user(request)

    try:
        object_id = ObjectId(video_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid video ID.",
        )

    video = videos_collection.find_one(
        {"_id": object_id}
    )

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    existing = likes_collection.find_one(
        {
            "videoId": object_id,
            "userId": user["_id"],
        }
    )

    if existing:
        likes_collection.delete_one(
            {"_id": existing["_id"]}
        )

        videos_collection.update_one(
            {"_id": object_id},
            {"$inc": {"likes": -1}},
        )

        liked = False

    else:
        likes_collection.insert_one(
            {
                "videoId": object_id,
                "userId": user["_id"],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        videos_collection.update_one(
            {"_id": object_id},
            {"$inc": {"likes": 1}},
        )

        liked = True

    updated = videos_collection.find_one(
        {"_id": object_id}
    )

    await manager.broadcast(
        {
            "type": "like_update",
            "videoId": video_id,
            "likes": updated.get("likes", 0),
        }
    )

    return {
        "liked": liked,
        "likes": updated.get("likes", 0),
    }


@app.get("/api/videos/{video_id}/liked")
async def is_liked(
    video_id: str,
    request: Request,
):
    user = get_current_user(request)

    try:
        object_id = ObjectId(video_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid video ID.",
        )

    liked = likes_collection.find_one(
        {
            "videoId": object_id,
            "userId": user["_id"],
        }
    )

    return {
        "liked": bool(liked)
    }

@app.get("/api/videos/{video_id}/comments")
async def get_comments(video_id: str):
    try:
        video = await db.videos.find_one({"_id": ObjectId(video_id)})

        if not video:
            raise HTTPException(status_code=404, detail="Видео не найдено")

        comments = []

        cursor = db.comments.find(
            {"video_id": video_id}
        ).sort("created_at", -1)

        async for comment in cursor:
            comments.append({
                "id": str(comment["_id"]),
                "video_id": comment["video_id"],
                "user_id": comment["user_id"],
                "username": comment.get("username", "Пользователь"),
                "avatar": comment.get("avatar"),
                "text": comment["text"],
                "created_at": comment["created_at"].isoformat()
            })

        return {
            "comments": comments,
            "count": len(comments)
        }

    except Exception as e:
        print("Ошибка получения комментариев:", e)
        raise HTTPException(
            status_code=500,
            detail="Не удалось загрузить комментарии"
        )


@app.post("/api/videos/{video_id}/comments")
async def add_comment(
    video_id: str,
    request: Request
):
    data = await request.json()

    user_id = data.get("user_id")
    text = data.get("text", "").strip()

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Необходимо войти в аккаунт"
        )

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Комментарий не может быть пустым"
        )

    if len(text) > 1000:
        raise HTTPException(
            status_code=400,
            detail="Комментарий слишком длинный"
        )

    try:
        video = await db.videos.find_one({
            "_id": ObjectId(video_id)
        })

        if not video:
            raise HTTPException(
                status_code=404,
                detail="Видео не найдено"
            )

        user = await db.users.find_one({
            "_id": ObjectId(user_id)
        })

        if not user:
            raise HTTPException(
                status_code=404,
                detail="Пользователь не найден"
            )

        comment = {
            "video_id": video_id,
            "user_id": user_id,
            "username": user.get("username", "Пользователь"),
            "avatar": user.get("avatar"),
            "text": text,
            "created_at": datetime.utcnow()
        }

        result = await db.comments.insert_one(comment)

        return {
            "success": True,
            "comment": {
                "id": str(result.inserted_id),
                "video_id": video_id,
                "user_id": user_id,
                "username": user.get("username", "Пользователь"),
                "avatar": user.get("avatar"),
                "text": text,
                "created_at": comment["created_at"].isoformat()
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        print("Ошибка добавления комментария:", e)
        raise HTTPException(
            status_code=500,
            detail="Не удалось добавить комментарий"
        )


@app.delete("/api/comments/{comment_id}")
async def delete_comment(
    comment_id: str,
    request: Request
):
    data = await request.json()

    user_id = data.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Необходимо войти в аккаунт"
        )

    try:
        comment = await db.comments.find_one({
            "_id": ObjectId(comment_id)
        })

        if not comment:
            raise HTTPException(
                status_code=404,
                detail="Комментарий не найден"
            )

        if comment["user_id"] != user_id:
            raise HTTPException(
                status_code=403,
                detail="Вы не можете удалить этот комментарий"
            )

        await db.comments.delete_one({
            "_id": ObjectId(comment_id)
        })

        return {
            "success": True,
            "message": "Комментарий удалён"
        }

    except HTTPException:
        raise

    except Exception as e:
        print("Ошибка удаления комментария:", e)
        raise HTTPException(
            status_code=500,
            detail="Не удалось удалить комментарий"
        )


# -----------------------------
# WebSocket
# -----------------------------

connected_users = set()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    connected_users.add(websocket)

    try:
        while True:
            data = await websocket.receive_json()

            # Пока просто пересылаем сообщение всем подключённым
            for user in connected_users:
                try:
                    await user.send_json(data)
                except Exception:
                    pass

    except WebSocketDisconnect:
        connected_users.discard(websocket)

    except Exception as e:
        print("WebSocket error:", e)
        connected_users.discard(websocket)


# -----------------------------
# Запуск
# -----------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000))
    )
