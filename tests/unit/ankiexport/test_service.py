"""
Service tests.
"""

import json
from unittest.mock import Mock, patch, MagicMock, call
import pytest
import requests # For requests.exceptions.RequestException
from lute.models.srsexport import SrsExportSpec
from lute.ankiexport.service import Service
from lute.ankiexport.exceptions import AnkiExportConfigurationError
from lute.models.term import Term, Status as LuteStatus
from lute.models.repositories import TermRepository

# pylint: disable=missing-function-docstring

@pytest.fixture(name="export_spec")
def fixture_spec():
    spec = SrsExportSpec()
    spec.id = 1
    spec.export_name = "export_name"
    spec.criteria = 'language:"German"'
    spec.deck_name = "good_deck"
    spec.note_type = "good_note"
    spec.field_mapping = json.dumps({"a": "{ language }"})
    spec.active = True
    return spec


def test_validate_returns_empty_hash_if_all_ok(export_spec):
    anki_decks = ["good_deck"]
    anki_notes = {"good_note": ["a", "b"]}
    svc = Service(anki_decks, anki_notes, [export_spec])
    result = svc.validate_specs()
    assert len(result) == 0, "No problems"
    msg = svc.validate_specs_failure_message()
    assert len(msg) == 0, "failure msg"


@pytest.mark.parametrize(
    "prop_name,prop_value,expected_error",
    [
        (
            "criteria",
            'lanxxguage:"German"',
            'Criteria syntax error at position 0 or later: lanxxguage:"German"',
        ),
        ("deck_name", "missing_deck", 'No deck name "missing_deck"'),
        ("note_type", "missing_note", 'No note type "missing_note"'),
        (
            "field_mapping",
            json.dumps({"xx": "{ language }"}),
            "Note type good_note does not have field(s): xx",
        ),
        (
            "field_mapping",
            json.dumps({"a": "{ bad_value }"}),
            'Invalid field mapping "bad_value"',
        ),
        (
            "field_mapping",
            "this_is_not_valid_json",
            "Mapping is not valid json",
        ),
    ],
)
def test_validate_spec_returns_array_of_errors( # pylint: disable=too-many-locals
    prop_name, prop_value, expected_error, export_spec
):
    anki_decks = ["good_deck"]
    anki_notes = {"good_note": ["a", "b"]}
    setattr(export_spec, prop_name, prop_value)
    svc = Service(anki_decks, anki_notes, [export_spec])
    result = svc.validate_spec(export_spec)
    assert result == [expected_error]

    export_spec.active = False
    assert len(svc.validate_spec(export_spec)) == 0, "no errors for inactive spec"


def test_validate_specs_returns_dict_of_export_ids_and_errors(export_spec):
    anki_decks = ["good_deck"]
    anki_notes = {"good_note": ["a", "b"]}
    export_spec.deck_name = "missing_deck"
    svc = Service(anki_decks, anki_notes, [export_spec])
    result = svc.validate_specs()
    assert result == {export_spec.id: 'No deck name "missing_deck"'}

    msg = svc.validate_specs_failure_message()
    assert msg == ['export_name: No deck name "missing_deck"'], "failure msg"


def test_validate_only_checks_active_specs(export_spec):
    anki_decks = ["good_deck"]
    anki_notes = {"good_note": ["a", "b"]}
    export_spec.criteria = "xxx={yyy}"
    svc = Service(anki_decks, anki_notes, [export_spec])
    result = svc.validate_specs()
    assert export_spec.id in result, "should have a problem, sanity check"

    export_spec.active = False
    result = svc.validate_specs()
    assert len(result) == 0, "No problems"
    msg = svc.validate_specs_failure_message()
    assert len(msg) == 0, "failure msg"


@pytest.fixture(name="term")
def fixture_term():
    zws = "\u200B"
    term = Mock()
    term.id = 1
    term.text = f"test{zws} {zws}term"
    term.status = 1
    term.romanization = "blah-blah"
    term.language = Mock() # Ensure language is a Mock object
    term.language.name = "German"
    term.language.id = 42
    term.get_current_image.return_value = "image.jpg"
    term.term_tags = [Mock(text="noun"), Mock(text="verb")]
    term.translation = f"example{zws} {zws}translation"

    parent = Mock()
    parent.text = "parent-text"
    parent.translation = "parent-transl"
    parent.romanization = "parent-blah"
    parent.get_current_image.return_value = None
    parent.term_tags = [Mock(text="parenttag"), Mock(text="xyz")]
    term.parents = [parent]

    return term


def test_smoke_ankiconnect_post_data_for_term(term, export_spec): # pylint: disable=too-many-locals
    anki_decks = ["good_deck"]
    anki_notes = {"good_note": ["a", "b", "c", "d", "e", "f", "g", "h"]}
    export_spec.field_mapping = json.dumps(
        {
            "a": "{ language }",
            "b": "{ image }",
            "c": "{ term }",
            "d": "{ sentence }",
            "e": "{ pronunciation }",
            "f": '{ tags:["noun"] }',
            "g": '{ parents.tags:["parenttag"] }',
            "h": "{ parents.pronunciation }",
        }
    )
    svc = Service(anki_decks, anki_notes, [export_spec])
    result = svc.validate_specs()
    assert len(result) == 0, "No problems, sanity check"

    sentence_lookup = Mock()
    sentence_lookup.get_sentence_for_term.return_value = "Example sentence."

    pd = svc.get_ankiconnect_post_data_for_term(term, "http://x:42", sentence_lookup)
    assert len(pd) != 0, "Got some post data"

    expected = {
        "export_name": {
            "action": "multi",
            "params": {
                "actions": [
                    {
                        "action": "storeMediaFile",
                        "params": {
                            "filename": "LUTE_TERM_1.jpg",
                            "url": "http://x:42/userimages/42/image.jpg",
                        },
                    },
                    {
                        "action": "addNote",
                        "params": {
                            "note": {
                                "deckName": "good_deck",
                                "modelName": "good_note",
                                "fields": {
                                    "a": "German",
                                    "b": '<img src="LUTE_TERM_1.jpg">',
                                    "c": "test term",
                                    "d": "Example sentence.",
                                    "e": "blah-blah",
                                    "f": "noun",
                                    "g": "parenttag",
                                    "h": "parent-blah",
                                },
                                "tags": ["lute", "noun", "parenttag", "verb", "xyz"],
                            }
                        },
                    },
                ]
            },
        }
    }
    assert pd == expected, "PHEW!"


def test_ankiconnect_post_data_for_term_with_status_mapping(term, export_spec): # pylint: disable=too-many-locals
    """
    Test that term status is correctly mapped if status_field is set.
    """
    anki_decks = ["good_deck"]
    anki_notes = {"good_note": ["a", "b", "StatusField"]}
    export_spec.field_mapping = json.dumps(
        {
            "a": "{ language }",
            "b": "{ term }",
        }
    )
    export_spec.status_field = "StatusField"

    svc = Service(anki_decks, anki_notes, [export_spec])
    assert len(svc.validate_specs()) == 0, "No problems, sanity check"

    sentence_lookup = Mock()
    sentence_lookup.get_sentence_for_term.return_value = "Sentence."

    pd = svc.get_ankiconnect_post_data_for_term(term, "http://x:42", sentence_lookup)

    expected_fields = {
        "a": "German",
        "b": "test term",
        "StatusField": 1,
    }
    actual_note = pd["export_name"]["params"]["actions"][0]["params"]["note"]
    # If media files are present, actions list could be longer.
    if pd["export_name"]["params"]["actions"][0]["action"] != "addNote":
        actual_note = pd["export_name"]["params"]["actions"][1]["params"]["note"]
    assert actual_note["fields"] == expected_fields

    export_spec.status_field = ""
    svc = Service(anki_decks, anki_notes, [export_spec])
    pd_empty_status_field = svc.get_ankiconnect_post_data_for_term(term, "http://x:42", sentence_lookup)
    expected_fields_no_status = {"a": "German", "b": "test term"}
    actual_note_empty_status = pd_empty_status_field["export_name"]["params"]["actions"][0]["params"]["note"]
    if pd_empty_status_field["export_name"]["params"]["actions"][0]["action"] != "addNote":
        actual_note_empty_status = pd_empty_status_field["export_name"]["params"]["actions"][1]["params"]["note"]
    assert actual_note_empty_status["fields"] == expected_fields_no_status

    export_spec.status_field = "   "
    svc = Service(anki_decks, anki_notes, [export_spec])
    pd_whitespace_status_field = svc.get_ankiconnect_post_data_for_term(term, "http://x:42", sentence_lookup)
    actual_note_whitespace_status = pd_whitespace_status_field["export_name"]["params"]["actions"][0]["params"]["note"]
    if pd_whitespace_status_field["export_name"]["params"]["actions"][0]["action"] != "addNote":
        actual_note_whitespace_status = pd_whitespace_status_field["export_name"]["params"]["actions"][1]["params"]["note"]
    assert actual_note_whitespace_status["fields"] == expected_fields_no_status


def test_smoke_ankiconnect_post_data_for_term_without_image(term, export_spec): # pylint: disable=too-many-locals
    term.get_current_image.return_value = None

    anki_decks = ["good_deck"]
    anki_notes = {"good_note": ["a", "b", "c", "d"]}
    export_spec.field_mapping = json.dumps(
        {
            "a": "{ language }",
            "b": "{ image }",
            "c": "{ term }",
            "d": "{ sentence }",
        }
    )
    svc = Service(anki_decks, anki_notes, [export_spec])
    result = svc.validate_specs()
    assert len(result) == 0, "No problems, sanity check"

    sentence_lookup = Mock()
    sentence_lookup.get_sentence_for_term.return_value = "Example sentence."

    pd = svc.get_ankiconnect_post_data_for_term(term, "http://x:42", sentence_lookup)
    assert len(pd) != 0, "Got some post data"

    expected = {
        "export_name": {
            "action": "multi",
            "params": {
                "actions": [
                    {
                        "action": "addNote",
                        "params": {
                            "note": {
                                "deckName": "good_deck",
                                "modelName": "good_note",
                                "fields": {
                                    "a": "German",
                                    "c": "test term",
                                    "d": "Example sentence.",
                                },
                                "tags": ["lute", "noun", "parenttag", "verb", "xyz"],
                            }
                        },
                    },
                ]
            },
        }
    }
    assert pd == expected, "PHEW!"


# Tests for import_anki_statuses

@pytest.fixture(name="svc")
def fixture_service():
    """A Service instance for testing import_anki_statuses."""
    return Service(anki_deck_names=[], anki_note_types_and_fields={}, export_specs=[])

def _create_term(language, text, status, term_repo):
    """Helper to create and save a term."""
    term = Term(language, text)
    term.status = status
    term_repo.add(term)
    term_repo.commit() # Committing here to get an ID for the term
    return term

def mock_ankiconnect_response_generator(ankiconnect_actions_results):
    """
    Creates a mock for requests.post that cycles through predefined results
    for AnkiConnect actions.
    ankiconnect_actions_results should be a list of dictionaries,
    where each dict is like {"action": "findCards", "result": [1, 2]}
    or {"action": "cardsInfo", "error": "some error"}
    """
    results_iter = iter(ankiconnect_actions_results)

    def mock_post_fn(url, json: dict, timeout): # pylint: disable=unused-argument, redefined-outer-name
        mock_resp = MagicMock()
        current_action_spec = next(results_iter)

        if json["action"] != current_action_spec["action"]:
            raise AssertionError(
                f"Expected AnkiConnect action {current_action_spec['action']} "
                f"but got {json['action']}"
            )

        if "error" in current_action_spec:
            mock_resp.json.return_value = {"result": None, "error": current_action_spec["error"]}
        else:
            mock_resp.json.return_value = {"result": current_action_spec["result"], "error": None}
        
        if "http_error_code" in current_action_spec:
            mock_resp.status_code = current_action_spec["http_error_code"]
            mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
                f"HTTP Error {current_action_spec['http_error_code']}"
            )
        else:
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None

        return mock_resp
    return mock_post_fn


@patch('lute.ankiexport.service.requests.post')
def test_import_anki_statuses_success(mock_post, svc, english, app_context): # pylint: disable=too-many-locals
    db_session = app_context.db.session
    term_repo = TermRepository(db_session)
    term1 = _create_term(english, "apple", LuteStatus.UNKNOWN, term_repo)

    find_cards_response = {"action": "findCards", "result": [101]}
    cards_info_response = {
        "action": "cardsInfo",
        "result": [{
            "cardId": 101, "note": 201, "deckName": "English", "modelName": "Basic",
            "fields": {"LuteTermID": {"value": str(term1.id), "order": 0}},
            "ivl": 0, "type": 0, "queue": 0, "due": 0, "reps": 0, "lapses": 0
        }]
    }
    mock_post.side_effect = mock_ankiconnect_response_generator([find_cards_response, cards_info_response])

    result = svc.import_anki_statuses(
        db_session=db_session,
        anki_tag_name="LuteExport",
        lute_term_id_field="LuteTermID"
    )

    assert result["lute_terms_updated"] == 1
    assert result["cards_processed"] == 1
    updated_term1 = term_repo.find(term1.id)
    assert updated_term1.status == 1

    expected_find_payload = {"action": "findCards", "version": 6, "params": {"query": "tag:LuteExport"}}
    expected_info_payload = {"action": "cardsInfo", "version": 6, "params": {"cards": [101]}}
    
    call_args_list = mock_post.call_args_list
    assert call_args_list[0].kwargs['json'] == expected_find_payload
    assert call_args_list[1].kwargs['json'] == expected_info_payload


@patch('lute.ankiexport.service.requests.post')
def test_import_anki_statuses_no_cards_found(mock_post, svc, app_context):
    db_session = app_context.db.session
    find_cards_response = {"action": "findCards", "result": []}
    mock_post.side_effect = mock_ankiconnect_response_generator([find_cards_response])

    result = svc.import_anki_statuses(
        db_session=db_session,
        anki_tag_name="LuteExport",
        lute_term_id_field="LuteTermID"
    )
    assert result["message"] == "No cards found in Anki matching the criteria."
    assert result["updated_count"] == 0
    mock_post.assert_called_once()


@patch('lute.ankiexport.service.requests.post')
def test_import_anki_statuses_lute_term_not_found(mock_post, svc, app_context): # pylint: disable=too-many-locals
    db_session = app_context.db.session
    find_cards_response = {"action": "findCards", "result": [102]}
    cards_info_response = {
        "action": "cardsInfo",
        "result": [{
            "cardId": 102, "fields": {"LuteTermID": {"value": "9999"}}, 
            "ivl": 0, "type": 0, "queue": 0, "note": 202, "deckName": "D", "modelName": "M"
        }]
    }
    mock_post.side_effect = mock_ankiconnect_response_generator([find_cards_response, cards_info_response])

    result = svc.import_anki_statuses(
        db_session=db_session, anki_tag_name="LuteExport", lute_term_id_field="LuteTermID"
    )
    assert result["lute_terms_updated"] == 0
    assert result["lute_terms_not_found"] == 1
    assert result["cards_processed"] == 1


@patch('lute.ankiexport.service.requests.post')
def test_import_anki_statuses_ankiconnect_request_exception(mock_post, svc, app_context):
    db_session = app_context.db.session
    mock_post.side_effect = requests.exceptions.RequestException("Connection failed")

    with pytest.raises(AnkiExportConfigurationError, match="Failed to connect to AnkiConnect: Connection failed"):
        svc.import_anki_statuses(
            db_session=db_session, anki_tag_name="LuteExport", lute_term_id_field="LuteTermID"
        )


@patch('lute.ankiexport.service.requests.post')
def test_import_anki_statuses_ankiconnect_api_error(mock_post, svc, app_context):
    db_session = app_context.db.session
    find_cards_response = {"action": "findCards", "error": "Invalid query"}
    mock_post.side_effect = mock_ankiconnect_response_generator([find_cards_response])
    
    with pytest.raises(AnkiExportConfigurationError, match="AnkiConnect error: Invalid query"):
        svc.import_anki_statuses(
            db_session=db_session, anki_tag_name="LuteExport", lute_term_id_field="LuteTermID"
        )


@patch('lute.ankiexport.service.requests.post')
def test_import_anki_statuses_various_mappings_and_no_ops(mock_post, svc, english, app_context): # pylint: disable=too-many-locals
    db_session = app_context.db.session
    term_repo = TermRepository(db_session)

    term_new_to_learning = _create_term(english, "term_new", LuteStatus.UNKNOWN, term_repo)
    term_learning_same = _create_term(english, "term_learn", 1, term_repo)
    term_review_to_known = _create_term(english, "term_rev_known", 1, term_repo)
    term_review_to_wellknown5 = _create_term(english, "term_rev_wk5", 3, term_repo)
    term_suspended_to_ignored = _create_term(english, "term_susp", 1, term_repo)
    term_buried_no_change = _create_term(english, "term_buried", 2, term_repo)

    anki_cards_data = [
        {"cardId": 101, "fields": {"LuteTermID": {"value": str(term_new_to_learning.id)}}, "ivl": 0, "type": 0, "queue": 0},
        {"cardId": 102, "fields": {"LuteTermID": {"value": str(term_learning_same.id)}}, "ivl": 0, "type": 1, "queue": 1},
        {"cardId": 103, "fields": {"LuteTermID": {"value": str(term_review_to_known.id)}}, "ivl": 10, "type": 2, "queue": 2},
        {"cardId": 104, "fields": {"LuteTermID": {"value": str(term_review_to_wellknown5.id)}}, "ivl": 100, "type": 2, "queue": 2},
        {"cardId": 105, "fields": {"LuteTermID": {"value": str(term_suspended_to_ignored.id)}}, "ivl": 5, "type": 2, "queue": -1},
        {"cardId": 106, "fields": {"LuteTermID": {"value": str(term_buried_no_change.id)}}, "ivl": 5, "type": 2, "queue": -2},
        {"cardId": 107, "fields": {"OtherField": {"value": "some_val"}}, "ivl": 0, "type": 0, "queue": 0},
        {"cardId": 108, "fields": {"LuteTermID": {"value": "xyz"}}, "ivl": 0, "type": 0, "queue": 0},
        {"cardId": 109, "fields": {"LuteTermID": {"value": "999"}}, "ivl": 0, "type": 0, "queue": 0},
    ]
    
    for card_d in anki_cards_data: # Ensure all cards have basic fields AnkiConnect provides
        card_d.setdefault("note", card_d["cardId"] + 1000) 
        card_d.setdefault("deckName", "Default")
        card_d.setdefault("modelName", "Basic")

    find_cards_response = {"action": "findCards", "result": [c["cardId"] for c in anki_cards_data]}
    cards_info_response = {"action": "cardsInfo", "result": anki_cards_data}
    mock_post.side_effect = mock_ankiconnect_response_generator([find_cards_response, cards_info_response])

    result = svc.import_anki_statuses(
        db_session=db_session, anki_tag_name="LuteExport", lute_term_id_field="LuteTermID", anki_deck_name="TestDeck"
    )

    assert result["cards_processed"] == len(anki_cards_data)
    assert result["lute_terms_updated"] == 4
    assert result["lute_terms_not_found"] == 1 
    assert result["anki_cards_unmapped_or_error"] == 3

    assert term_repo.find(term_new_to_learning.id).status == 1
    assert term_repo.find(term_learning_same.id).status == 1 
    assert term_repo.find(term_review_to_known.id).status == 3
    assert term_repo.find(term_review_to_wellknown5.id).status == 5
    assert term_repo.find(term_suspended_to_ignored.id).status == LuteStatus.IGNORED
    assert term_repo.find(term_buried_no_change.id).status == 2 
    
    expected_find_payload = {"action": "findCards", "version": 6, "params": {"query": 'tag:LuteExport deck:"TestDeck"'}}
    assert mock_post.call_args_list[0].kwargs['json'] == expected_find_payload
