from fastapi import APIRouter, HTTPException

from app.services.ai_case_store import build_case_response, list_cases

router = APIRouter(prefix="/api/cases", tags=["ai-cases"])

@router.get("")
def get_cases():
    cases = list_cases()
    return {
        "count": len(cases),
        "cases": [
            {
                "case_id": c.get("case_id"),
                "source_disease": c.get("source_disease"),
                "is_positive_gt": c.get("is_positive_gt"),
                "prediction_count": c.get("prediction_count", 0),
            }
            for c in cases
        ],
    }

@router.get("/{case_id}")
def get_case(case_id: str):
    try:
        return build_case_response(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="AI_CASE_NOT_FOUND")
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"AI_DATA_FILE_NOT_FOUND: {e.name}")
