from fastapi import APIRouter, Depends, HTTPException, status

from src.helpers import repo
from src.helpers.hub import hub
from src.middlewares.auth import require_admin

router = APIRouter(prefix="/api/devices", tags=["devices"], dependencies=[Depends(require_admin)])


@router.get("")
def list_devices():
    return hub.device_list()


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: int):
    if not repo.delete_device(device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispositivo no encontrado")
    hub.disconnect_device(device_id)
    hub.broadcast_devices()
