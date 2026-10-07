from fastapi import Request

from app.services.file_service import FileService


def get_file_service(request: Request) -> FileService:
    return request.app.state.file_service
