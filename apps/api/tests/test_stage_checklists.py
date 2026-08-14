import json

import pytest

from app.services.stage_checklists import _object_without_duplicate_keys


def test_stage_checklist_contract_parser_rejects_duplicate_keys():
    with pytest.raises(ValueError, match="Duplicate key in stage checklist contract: progress_review"):
        json.loads(
            '{"progress_review": [], "progress_review": []}',
            object_pairs_hook=_object_without_duplicate_keys,
        )
