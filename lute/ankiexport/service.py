"""
Service, validates and posts.
"""

import json
import requests # For AnkiConnect
from lute.models.repositories import TermRepository
from lute.models.term import Term, Status as LuteStatus # For updating Term status
from lute.term.model import ReferencesRepository
from lute.ankiexport.exceptions import AnkiExportConfigurationError
from lute.ankiexport.field_mapping import (
    get_values_and_media_mapping,
    validate_mapping,
    get_fields_and_final_values,
    SentenceLookup,
)
from lute.ankiexport.criteria import (
    evaluate_criteria,
    validate_criteria,
)


class Service:
    "Srs export service."

    def __init__(
        self,
        anki_deck_names,
        anki_note_types_and_fields,
        export_specs,
    ):
        "init"
        self.anki_deck_names = anki_deck_names
        self.anki_note_types_and_fields = anki_note_types_and_fields
        self.export_specs = export_specs

    def validate_spec(self, spec):
        """
        Returns array of errors if any for the given spec.
        """
        if not spec.active:
            return []

        errors = []

        try:
            validate_criteria(spec.criteria)
        except AnkiExportConfigurationError as ex:
            errors.append(str(ex))

        if spec.deck_name not in self.anki_deck_names:
            errors.append(f'No deck name "{spec.deck_name}"')

        valid_note_type = spec.note_type in self.anki_note_types_and_fields
        if not valid_note_type:
            errors.append(f'No note type "{spec.note_type}"')

        mapping = None
        try:
            mapping = json.loads(spec.field_mapping)
        except json.decoder.JSONDecodeError:
            errors.append("Mapping is not valid json")

        if valid_note_type and mapping:
            note_fields = self.anki_note_types_and_fields.get(spec.note_type, {})
            bad_fields = [f for f in mapping.keys() if f not in note_fields]
            if len(bad_fields) > 0:
                bad_fields = ", ".join(bad_fields)
                msg = f"Note type {spec.note_type} does not have field(s): {bad_fields}"
                errors.append(msg)

        if mapping:
            try:
                validate_mapping(json.loads(spec.field_mapping))
            except AnkiExportConfigurationError as ex:
                errors.append(str(ex))

        return errors

    def validate_specs(self):
        """
        Return hash of spec ids and any config errors.
        """
        failures = {}
        for spec in self.export_specs:
            v = self.validate_spec(spec)
            if len(v) != 0:
                failures[spec.id] = "; ".join(v)
        return failures

    def validate_specs_failure_message(self):
        "Failure message for alerts."
        failures = self.validate_specs()
        msgs = []
        for k, v in failures.items():
            spec = next(s for s in self.export_specs if s.id == k)
            msgs.append(f"{spec.export_name}: {v}")
        return msgs

    def _all_terms(self, term):
        "Term and any parents."
        ret = [term]
        ret.extend(term.parents)
        return ret

    def _all_tags(self, term):
        "Tags for term and all parents."
        ret = [tt.text for t in self._all_terms(term) for tt in t.term_tags]
        return sorted(list(set(ret)))

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _build_ankiconnect_post_json(
        self,
        mapping,
        media_mappings,
        lute_and_term_tags,
        deck_name,
        model_name,
    ):
        "Build post json for term using the mappings."

        post_actions = []
        for new_filename, original_url in media_mappings.items():
            hsh = {
                "action": "storeMediaFile",
                "params": {
                    "filename": new_filename,
                    "url": original_url,
                },
            }
            post_actions.append(hsh)

        post_actions.append(
            {
                "action": "addNote",
                "params": {
                    "note": {
                        "deckName": deck_name,
                        "modelName": model_name,
                        "fields": mapping,
                        "tags": lute_and_term_tags,
                    }
                },
            }
        )

        return {"action": "multi", "params": {"actions": post_actions}}

    def get_ankiconnect_post_data_for_term(self, term, base_url, sentence_lookup):
        """
        Get post data for a single term.
        This assumes that all the specs are valid!
        Separate method for unit testing.
        """
        use_exports = [
            spec
            for spec in self.export_specs
            if spec.active and evaluate_criteria(spec.criteria, term)
        ]
        # print(f"Using {len(use_exports)} exports")

        ret = {}
        for export in use_exports:
            mapping = json.loads(export.field_mapping)
            replacements, mmap = get_values_and_media_mapping(
                term, sentence_lookup, mapping
            )
            for k, v in mmap.items():
                mmap[k] = base_url + v
            updated_mapping = get_fields_and_final_values(mapping, replacements)

            # Add term status if mapping is provided
            if export.status_field and export.status_field.strip() != "":
                if "status" in replacements:
                    updated_mapping[export.status_field.strip()] = replacements["status"]

            tags = ["lute"] + self._all_tags(term)

            p = self._build_ankiconnect_post_json(
                updated_mapping,
                mmap,
                tags,
                export.deck_name,
                export.note_type,
            )
            ret[export.export_name] = p

        return ret

    def get_ankiconnect_post_data(
        self, term_ids, termid_sentences, base_url, db_session
    ):
        """
        Build data to be posted.

        Throws if any validation failure or mapping failure, as it's
        annoying to handle partial failures.
        """

        msgs = self.validate_specs_failure_message()
        if len(msgs) > 0:
            show_msgs = [f"* {m}" for m in msgs]
            show_msgs = "\n".join(show_msgs)
            err_msg = "Anki export configuration errors:\n" + show_msgs
            raise AnkiExportConfigurationError(err_msg)

        repo = TermRepository(db_session)

        refsrepo = ReferencesRepository(db_session)
        sentence_lookup = SentenceLookup(termid_sentences, refsrepo)

        ret = {}
        for tid in term_ids:
            term = repo.find(tid)
            pd = self.get_ankiconnect_post_data_for_term(
                term, base_url, sentence_lookup
            )
            if len(pd) > 0:
                ret[tid] = pd

        return ret

    def _anki_connect_request(self, action, params=None):
        """Helper to make requests to AnkiConnect."""
        payload = {"action": action, "version": 6}
        if params:
            payload["params"] = params
        try:
            response = requests.post("http://localhost:8765", json=payload, timeout=5)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            result = response.json()
            if result.get("error") is not None:
                raise AnkiExportConfigurationError(f"AnkiConnect error: {result['error']}")
            return result.get("result")
        except requests.exceptions.RequestException as e:
            # More specific error handling could be added here (e.g., connection error vs. timeout)
            raise AnkiExportConfigurationError(f"Failed to connect to AnkiConnect: {e}") from e

    def _map_anki_status_to_lute(self, anki_type, anki_queue, anki_ivl):
        """Maps Anki card status to Lute term status."""
        # Anki card types: 0=new, 1=learning, 2=due(review), 3=relearning
        # Anki card queues: 0=new, 1=learning, 2=due/rev, 3=day learn,
        #                  -1=suspended, -2=user buried, -3=sched buried
        # Lute Statuses: 1-5, WELLKNOWN=99, IGNORED=98

        if anki_queue == -1: # Suspended
            return LuteStatus.IGNORED
        if anki_queue in [-2, -3]: # Buried
            return None # No change

        if anki_type == 0: # New
            return 1 # Learning
        if anki_type == 1: # Learning
            return 1 # Learning
        if anki_type == 3: # Relearning
            return 1 # Learning
        
        if anki_type == 2: # Due/Review
            if anki_ivl < 7:
                return 2 # Learned
            if anki_ivl < 30:
                return 3 # Known
            if anki_ivl < 90:
                return 4 # Well-Known (Lute status 4)
            return 5 # Well-Known (Lute status 5 / "Five")

        return None # Default to no change if no mapping fits

    def import_anki_statuses(self, db_session, anki_tag_name, lute_term_id_field, anki_deck_name=None):
        """
        Imports learning statuses from Anki cards back to Lute terms.
        """
        term_repo = TermRepository(db_session)
        updated_count = 0
        not_found_lute_terms = 0
        unmapped_anki_cards = 0
        cards_processed = 0

        # 1. Find cards in Anki
        query = f"tag:{anki_tag_name}"
        if anki_deck_name:
            query += f' deck:"{anki_deck_name}"'
        
        card_ids = self._anki_connect_request("findCards", {"query": query})
        if not card_ids:
            return {"message": "No cards found in Anki matching the criteria.", "updated_count": 0}

        # 2. Get card info for found cards
        card_infos = self._anki_connect_request("cardsInfo", {"cards": card_ids})
        cards_processed = len(card_infos)

        for card_info in card_infos:
            lute_term_id_val = card_info["fields"].get(lute_term_id_field, {}).get("value")
            if not lute_term_id_val:
                # This card doesn't have the Lute Term ID field, or it's empty
                unmapped_anki_cards +=1
                continue

            try:
                lute_term_id = int(lute_term_id_val)
            except ValueError:
                # Invalid Term ID format
                unmapped_anki_cards +=1
                continue

            # 3. Map Anki status to Lute status
            anki_type = card_info["type"]
            anki_queue = card_info["queue"]
            anki_ivl = card_info["ivl"]
            
            new_lute_status = self._map_anki_status_to_lute(anki_type, anki_queue, anki_ivl)

            if new_lute_status is None:
                unmapped_anki_cards +=1
                continue

            # 4. Update Lute term
            term_to_update = term_repo.find(lute_term_id)
            if term_to_update:
                if term_to_update.status != new_lute_status:
                    term_to_update.status = new_lute_status
                    term_repo.add(term_to_update) # Add to session for commit
                    updated_count += 1
            else:
                not_found_lute_terms +=1
        
        if updated_count > 0:
            db_session.commit()

        return {
            "message": "Anki status sync completed.",
            "cards_processed": cards_processed,
            "lute_terms_updated": updated_count,
            "lute_terms_not_found": not_found_lute_terms,
            "anki_cards_unmapped_or_error": unmapped_anki_cards
        }
