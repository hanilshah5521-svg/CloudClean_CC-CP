from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import app.models.s3  # noqa: F401  (registers the S3 tables before init_db)
from app.core.database import get_db
from app.models import User
from app.security.session import get_current_user
from app.services import s3_service as svc

router = APIRouter(prefix="/api/s3", tags=["s3"])

# Least-privilege IAM policy for the keys a user connects (also shown in the UI).
IAM_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {"Sid": "CloudCleanAnalyze", "Effect": "Allow", "Resource": "*", "Action": [
            "s3:ListAllMyBuckets", "s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:GetLifecycleConfiguration",
            "s3:ListBucket", "s3:ListBucketVersions", "s3:ListBucketMultipartUploads", "s3:ListMultipartUploadParts",
        ]},
        {"Sid": "CloudCleanOptimize", "Effect": "Allow", "Resource": "*", "Action": [
            "s3:PutLifecycleConfiguration", "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject",
            "s3:DeleteObject", "s3:DeleteObjectVersion",
        ]},
    ],
}


class ConnectRequest(BaseModel):
    access_key_id: str = Field(min_length=16, max_length=128)
    secret_access_key: str = Field(min_length=16, max_length=128)
    region: str = Field("us-east-1", pattern=r"^[a-z]{2}(-[a-z]+)+-\d$")


class TrashRequest(BaseModel):
    bucket_id: int
    group: int
    keep_object_id: int


def _run(fn, *args):
    try:
        return fn(*args)
    except (svc.S3Error, svc.S3AccessError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except svc.AWS_ERRORS as exc:
        raise HTTPException(status_code=502, detail=svc.describe_error(exc)) from exc


@router.get("/iam-policy")
def iam_policy():
    return IAM_POLICY


@router.get("")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.overview(db, user)


@router.post("/connect")
def connect(body: ConnectRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _run(svc.connect, db, user, body.access_key_id, body.secret_access_key, body.region)
    return svc.overview(db, user)


@router.post("/connect-demo")
def connect_demo(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.connect_demo(db, user)
    return svc.overview(db, user)


@router.delete("/connection")
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.disconnect(db, user)
    return {"ok": True}


@router.post("/scan")
def scan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(svc.scan, db, user)


@router.get("/duplicates")
def duplicates(bucket_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.duplicate_groups(db, user, bucket_id)


@router.post("/duplicates/trash")
def trash_duplicates(body: TrashRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"results": _run(svc.trash_duplicates, db, user, body.bucket_id, body.group, body.keep_object_id)}


@router.get("/compression")
def compression(bucket_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.compression_candidates(db, user, bucket_id)


@router.post("/objects/{object_id}/compress")
def compress(object_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(svc.compress_object, db, user, object_id)


@router.get("/recommendations/{rec_id}/preview")
def preview(rec_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(svc.preview_recommendation, db, user, rec_id)


@router.post("/recommendations/{rec_id}/apply")
def apply(rec_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(svc.apply_recommendation, db, user, rec_id)


@router.get("/history")
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.history(db, user)


@router.post("/history/{action_id}/undo")
def undo(action_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _run(svc.undo_action, db, user, action_id)
