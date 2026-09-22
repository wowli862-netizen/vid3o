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

@app.get("/")
async def home():
    return FileResponse("index.html")


@app.get("/app.js")
async def javascript():
    return FileResponse("app.js")


@app.get("/style.css")
async def css():
    return FileResponse("style.css")

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
# USER PROFILE
# ============================================================

@app.get("/api/users/{username}")
async def get_user_profile(username: str):

    require_db()

    username = username.strip()

    if not username:
        raise HTTPException(
            status_code=400,
            detail="Username is required."
        )

    user = users_collection.find_one({
        "username": username
    })

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден."
        )

    videos = list(
        videos_collection
        .find({
            "ownerId": user["_id"]
        })
        .sort("createdAt", DESCENDING)
        .limit(100)
    )

    return {
        "user": serialize_user(user),
        "videos": [
            serialize_video(video)
            for video in videos
        ]
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
        "-threads", "1",
        "-i", str(input_path),

        # Ограничиваем разрешение
        "-vf", "scale='min(1280,iw)':-2",

        # Более лёгкое кодирование
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "30",
        "-tune", "zerolatency",

        # Минимум дополнительных буферов
        "-x264-params", "ref=1:bframes=0",

        # Аудио
        "-c:a", "aac",
        "-b:a", "96k",

        # Чтобы видео нормально начинало воспроизводиться из браузера
        "-movflags", "+faststart",

        str(output_path),
    ]

    subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=600,
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
            detail="Не удалось определить тип видео."
        )

    if not video.content_type.startswith("video/"):
        raise HTTPException(
            status_code=400,
            detail="Можно загружать только видеофайлы."
        )

    # Максимальный размер исходного файла — 100 MB.
    # Это защищает бесплатный сервер от слишком тяжёлых загрузок.
    MAX_VIDEO_SIZE = 100 * 1024 * 1024

    try:
        video.file.seek(0, 2)
        file_size = video.file.tell()
        video.file.seek(0)
    except Exception:
        file_size = 0

    if file_size > MAX_VIDEO_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Видео слишком большое. Максимальный размер — 100 МБ."
        )

    temporary_name = f"{uuid.uuid4().hex}_source"

    extension = Path(video.filename or ".mp4").suffix.lower()

    allowed_extensions = {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".m4v",
    }

    if extension not in allowed_extensions:
        extension = ".mp4"

    source_path = VIDEO_DIR / f"{temporary_name}{extension}"
    final_filename = f"{uuid.uuid4().hex}.mp4"
    final_path = VIDEO_DIR / final_filename

    try:
        # Копируем файл небольшими блоками,
        # не загружая всё видео в RAM.
        with open(source_path, "wb") as buffer:
            while True:
                chunk = video.file.read(1024 * 1024)

                if not chunk:
                    break

                buffer.write(chunk)

        # Перекодирование с ограниченным использованием ресурсов.
        await asyncio.to_thread(
            compress_video,
            source_path,
            final_path,
        )

    except subprocess.TimeoutExpired:
        if final_path.exists():
            final_path.unlink()

        raise HTTPException(
            status_code=500,
            detail="Обработка видео заняла слишком много времени."
        )

    except subprocess.CalledProcessError:
        if final_path.exists():
            final_path.unlink()

        raise HTTPException(
            status_code=500,
            detail="Не удалось обработать видео."
        )

    except Exception as error:
        if final_path.exists():
            final_path.unlink()

        print("VIDEO UPLOAD ERROR:", error)

        raise HTTPException(
            status_code=500,
            detail="Ошибка при загрузке видео."
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

    created = videos_collection.find_one({
        "_id": result.inserted_id
    })

    serialized_video = serialize_video(created)

    await manager.broadcast({
        "type": "new_video",
        "video": serialized_video,
    })

    return {
        "video": serialized_video
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
