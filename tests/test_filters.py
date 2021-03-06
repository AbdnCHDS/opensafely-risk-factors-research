import csv
import filecmp
import subprocess
import tempfile

import pytest

from tests.tpp_backend_setup import make_database, make_session
from tests.tpp_backend_setup import (
    CodedEvent,
    CovidStatus,
    MedicationIssue,
    MedicationDictionary,
    Patient,
    RegistrationHistory,
    Organisation,
    PatientAddress,
    ICNARC,
    ONSDeaths,
    CPNS,
)

from datalab_cohorts import StudyDefinition
from datalab_cohorts import patients
from datalab_cohorts import codelist
from datalab_cohorts import filter_codes_by_category
from datalab_cohorts import quote


def setup_module(module):
    make_database()


def setup_function(function):
    """Ensure test database is empty
    """
    session = make_session()
    session.query(CovidStatus).delete()
    session.query(CodedEvent).delete()
    session.query(ICNARC).delete()
    session.query(ONSDeaths).delete()
    session.query(CPNS).delete()
    session.query(MedicationIssue).delete()
    session.query(MedicationDictionary).delete()
    session.query(RegistrationHistory).delete()
    session.query(Organisation).delete()
    session.query(PatientAddress).delete()
    session.query(Patient).delete()
    session.commit()


def test_minimal_study_to_csv():
    session = make_session()
    patient_1 = Patient(DateOfBirth="1900-01-01", Sex="M")
    patient_2 = Patient(DateOfBirth="1900-01-01", Sex="F")
    session.add_all([patient_1, patient_2])
    session.commit()
    study = StudyDefinition(population=patients.all(), sex=patients.sex())
    with tempfile.NamedTemporaryFile(mode="w+") as f:
        study.to_csv(f.name)
        results = list(csv.DictReader(f))
        assert results == [
            {"patient_id": str(patient_1.Patient_ID), "sex": "M"},
            {"patient_id": str(patient_2.Patient_ID), "sex": "F"},
        ]


def test_patient_characteristics_for_covid_status():
    session = make_session()
    old_patient_with_covid = Patient(
        DateOfBirth="1900-01-01",
        CovidStatus=CovidStatus(Result="COVID19", AdmittedToITU=True),
        Sex="M",
    )
    young_patient_1_with_covid = Patient(
        DateOfBirth="2000-01-01",
        CovidStatus=CovidStatus(Result="COVID19", Died=True),
        Sex="F",
    )
    young_patient_2_without_covid = Patient(DateOfBirth="2001-01-01", Sex="F")
    session.add(old_patient_with_covid)
    session.add(young_patient_1_with_covid)
    session.add(young_patient_2_without_covid)
    session.commit()

    study = StudyDefinition(
        population=patients.with_positive_covid_test(),
        age=patients.age_as_of("2020-01-01"),
        sex=patients.sex(),
        died=patients.have_died_of_covid(),
    )
    results = study.to_dicts()

    assert [x["sex"] for x in results] == ["M", "F"]
    assert [x["died"] for x in results] == ["0", "1"]
    assert [x["age"] for x in results] == ["120", "20"]


def test_meds():
    session = make_session()

    asthma_medication = MedicationDictionary(
        FullName="Asthma Drug", DMD_ID="0", MultilexDrug_ID="0"
    )
    patient_with_med = Patient()
    patient_with_med.MedicationIssues = [
        MedicationIssue(MedicationDictionary=asthma_medication)
    ]
    patient_without_med = Patient()
    session.add(patient_with_med)
    session.add(patient_without_med)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        asthma_meds=patients.with_these_medications(
            codelist(asthma_medication.DMD_ID, "snomed")
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_meds"] for x in results] == ["1", "0"]


def test_meds_with_count():
    session = make_session()

    asthma_medication = MedicationDictionary(
        FullName="Asthma Drug", DMD_ID="0", MultilexDrug_ID="0"
    )
    patient_with_med = Patient()
    patient_with_med.MedicationIssues = [
        MedicationIssue(
            MedicationDictionary=asthma_medication, ConsultationDate="2010-01-01"
        ),
        MedicationIssue(
            MedicationDictionary=asthma_medication, ConsultationDate="2015-01-01"
        ),
        MedicationIssue(
            MedicationDictionary=asthma_medication, ConsultationDate="2018-01-01"
        ),
        MedicationIssue(
            MedicationDictionary=asthma_medication, ConsultationDate="2020-01-01"
        ),
    ]
    patient_without_med = Patient()
    session.add(patient_with_med)
    session.add(patient_without_med)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        asthma_meds=patients.with_these_medications(
            codelist(asthma_medication.DMD_ID, "snomed"),
            on_or_after="2012-01-01",
            return_number_of_matches_in_period=True,
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_meds"] for x in results] == ["3", "0"]


def _make_clinical_events_selection(condition_code, patient_dates=None):
    # The default configuration of patients and dates which some tests assume
    if patient_dates is None:
        patient_dates = ["2001-06-01", "2002-06-01", None]
    session = make_session()
    for dates in patient_dates:
        patient = Patient()
        if dates is None:
            dates = []
        elif isinstance(dates, str):
            dates = [dates]
        for date in dates:
            if isinstance(date, tuple):
                date, value = date
            else:
                value = 0.0
            patient.CodedEvents.append(
                CodedEvent(
                    CTV3Code=condition_code, ConsultationDate=date, NumericValue=value
                )
            )
        session.add(patient)
    session.commit()


def test_clinical_event_without_filters():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(condition_code)
    # No date criteria
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3")
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["1", "1", "0"]


def test_clinical_event_with_max_date():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(condition_code)
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"), on_or_before="2001-12-01"
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["1", "0", "0"]


def test_clinical_event_with_min_date():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(condition_code)
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"), on_or_after="2005-12-01"
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["0", "0", "0"]


def test_clinical_event_with_min_and_max_date():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(condition_code)
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"), between=["2001-12-01", "2002-06-01"]
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["0", "1", "0"]


def test_clinical_event_returning_first_date():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(
        condition_code,
        patient_dates=[
            None,
            # Include date before period starts, which should be ignored
            ["2001-01-01", "2002-06-01"],
            ["2001-06-01"],
        ],
    )
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"),
            between=["2001-12-01", "2002-06-01"],
            returning="date",
            find_first_match_in_period=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["", "2002-06-01", ""]


def test_clinical_event_returning_last_date():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(
        condition_code,
        patient_dates=[
            None,
            # Include date after period ends, which should be ignored
            ["2002-06-01", "2003-01-01"],
            ["2001-06-01"],
        ],
    )
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"),
            between=["2001-12-01", "2002-06-01"],
            returning="date",
            find_last_match_in_period=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["", "2002-06-01", ""]


def test_clinical_event_returning_year_only():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(condition_code)
    # No date criteria
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"),
            returning="date",
            find_first_match_in_period=True,
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["2001", "2002", ""]


def test_clinical_event_returning_year_and_month_only():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(condition_code)
    # No date criteria
    study = StudyDefinition(
        population=patients.all(),
        asthma_condition=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"),
            returning="date",
            find_first_match_in_period=True,
            include_month=True,
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_condition"] for x in results] == ["2001-06", "2002-06", ""]


def test_clinical_event_with_count():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(
        condition_code,
        patient_dates=[
            None,
            # Include date before period starts, which should be ignored
            ["2001-01-01", "2002-01-01", "2002-02-01", "2002-06-01"],
            ["2001-06-01"],
        ],
    )
    study = StudyDefinition(
        population=patients.all(),
        asthma_count=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"),
            between=["2001-12-01", "2002-06-01"],
            returning="number_of_matches_in_period",
            find_first_match_in_period=True,
            include_date_of_match=True,
            include_month=True,
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_count"] for x in results] == ["0", "3", "0"]
    assert [x["asthma_count_first_date"] for x in results] == ["", "2002-01", ""]


def test_clinical_event_with_code():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(
        condition_code,
        patient_dates=[
            None,
            # Include date before period starts, which should be ignored
            ["2001-01-01", "2002-01-01", "2002-02-01", "2002-06-01"],
            ["2001-06-01"],
        ],
    )
    study = StudyDefinition(
        population=patients.all(),
        latest_asthma_code=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"),
            between=["2001-12-01", "2002-06-01"],
            returning="code",
            find_last_match_in_period=True,
            include_date_of_match=True,
            include_month=True,
        ),
    )
    results = study.to_dicts()
    assert [x["latest_asthma_code"] for x in results] == ["0", condition_code, "0"]
    assert [x["latest_asthma_code_date"] for x in results] == ["", "2002-06", ""]


def test_clinical_event_with_numeric_value():
    condition_code = "ASTHMA"
    _make_clinical_events_selection(
        condition_code,
        patient_dates=[
            None,
            # Include date before period starts, which should be ignored
            [
                ("2001-01-01", 1),
                ("2002-01-01", 2),
                ("2002-02-01", 3),
                ("2002-06-01", 4),
            ],
            [("2001-06-01", 7)],
        ],
    )
    study = StudyDefinition(
        population=patients.all(),
        asthma_value=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3"),
            between=["2001-12-01", "2002-06-01"],
            returning="numeric_value",
            find_first_match_in_period=True,
            include_date_of_match=True,
            include_month=True,
        ),
    )
    results = study.to_dicts()
    assert [x["asthma_value"] for x in results] == ["0.0", "2.0", "0.0"]
    assert [x["asthma_value_date"] for x in results] == ["", "2002-01", ""]


def test_clinical_event_with_category():
    session = make_session()
    session.add_all(
        [
            Patient(),
            Patient(
                CodedEvents=[
                    CodedEvent(CTV3Code="foo1", ConsultationDate="2018-01-01"),
                    CodedEvent(CTV3Code="foo2", ConsultationDate="2020-01-01"),
                ]
            ),
            Patient(
                CodedEvents=[CodedEvent(CTV3Code="foo3", ConsultationDate="2019-01-01")]
            ),
        ]
    )
    session.commit()
    codes = codelist([("foo1", "A"), ("foo2", "B"), ("foo3", "C")], "ctv3")
    study = StudyDefinition(
        population=patients.all(),
        code_category=patients.with_these_clinical_events(
            codes,
            returning="category",
            find_last_match_in_period=True,
            include_date_of_match=True,
        ),
    )
    results = study.to_dicts()
    assert [x["code_category"] for x in results] == ["", "B", "C"]
    assert [x["code_category_date"] for x in results] == ["", "2020", "2019"]


def test_patient_registered_as_of():
    session = make_session()

    patient_registered_in_2001 = Patient()
    patient_registered_in_2002 = Patient()
    patient_unregistered_in_2002 = Patient()
    patient_registered_in_2001.RegistrationHistory = [
        RegistrationHistory(StartDate="2001-01-01", EndDate="9999-01-01")
    ]
    patient_registered_in_2002.RegistrationHistory = [
        RegistrationHistory(StartDate="2002-01-01", EndDate="9999-01-01")
    ]
    patient_unregistered_in_2002.RegistrationHistory = [
        RegistrationHistory(StartDate="2001-01-01", EndDate="2002-01-01")
    ]

    session.add(patient_registered_in_2001)
    session.add(patient_registered_in_2002)
    session.add(patient_unregistered_in_2002)
    session.commit()

    # No date criteria
    study = StudyDefinition(population=patients.registered_as_of("2002-03-02"))
    results = study.to_dicts()
    assert [x["patient_id"] for x in results] == [
        str(patient_registered_in_2001.Patient_ID),
        str(patient_registered_in_2002.Patient_ID),
    ]


def test_patients_registered_with_one_practice_between():
    session = make_session()

    patient_registered_in_2001 = Patient()
    patient_registered_in_2002 = Patient()
    patient_unregistered_in_2002 = Patient()
    patient_registered_in_2001.RegistrationHistory = [
        RegistrationHistory(StartDate="2001-01-01", EndDate="9999-01-01")
    ]
    patient_registered_in_2002.RegistrationHistory = [
        RegistrationHistory(StartDate="2002-01-01", EndDate="9999-01-01")
    ]
    patient_unregistered_in_2002.RegistrationHistory = [
        RegistrationHistory(StartDate="2001-01-01", EndDate="2002-01-01")
    ]

    session.add(patient_registered_in_2001)
    session.add(patient_registered_in_2002)
    session.add(patient_unregistered_in_2002)
    session.commit()

    study = StudyDefinition(
        population=patients.registered_with_one_practice_between(
            "2001-12-01", "2003-01-01"
        )
    )
    results = study.to_dicts()
    assert [x["patient_id"] for x in results] == [
        str(patient_registered_in_2001.Patient_ID)
    ]


@pytest.mark.parametrize("include_dates", ["none", "year", "month", "day"])
def test_simple_bmi(include_dates):
    session = make_session()

    weight_code = "X76C7"
    height_code = "XM01E"

    patient = Patient(DateOfBirth="1950-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=weight_code, NumericValue=50, ConsultationDate="2002-06-01")
    )
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=height_code, NumericValue=10, ConsultationDate="2001-06-01")
    )
    session.add(patient)
    session.commit()

    if include_dates == "none":
        bmi_date = None
        bmi_kwargs = {}
    elif include_dates == "year":
        bmi_date = "2002"
        bmi_kwargs = dict(include_measurement_date=True)
    elif include_dates == "month":
        bmi_date = "2002-06"
        bmi_kwargs = dict(include_measurement_date=True, include_month=True)
    elif include_dates == "day":
        bmi_date = "2002-06-01"
        bmi_kwargs = dict(
            include_measurement_date=True, include_month=True, include_day=True
        )
    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            on_or_after="1995-01-01", on_or_before="2005-01-01", **bmi_kwargs
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["0.5"]
    assert [x.get("BMI_date_measured") for x in results] == [bmi_date]


def test_bmi_rounded():
    session = make_session()

    weight_code = "X76C7"
    height_code = "XM01E"

    patient = Patient(DateOfBirth="1950-01-01")
    patient.CodedEvents.append(
        CodedEvent(
            CTV3Code=weight_code, NumericValue=10.12345, ConsultationDate="2001-06-01"
        )
    )
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=height_code, NumericValue=10, ConsultationDate="2000-02-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            "2005-01-01",
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["0.1"]
    assert [x["BMI_date_measured"] for x in results] == ["2001-06-01"]


def test_bmi_with_zero_values():
    session = make_session()

    weight_code = "X76C7"
    height_code = "XM01E"

    patient = Patient(DateOfBirth="1950-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=weight_code, NumericValue=0, ConsultationDate="2001-06-01")
    )
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=height_code, NumericValue=0, ConsultationDate="2001-06-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            on_or_after="1995-01-01",
            on_or_before="2005-01-01",
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["0.0"]
    assert [x["BMI_date_measured"] for x in results] == ["2001-06-01"]


def test_explicit_bmi_fallback():
    session = make_session()

    weight_code = "X76C7"
    bmi_code = "22K.."

    patient = Patient(DateOfBirth="1950-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=weight_code, NumericValue=50, ConsultationDate="2001-06-01")
    )
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=bmi_code, NumericValue=99, ConsultationDate="2001-10-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            on_or_after="1995-01-01",
            on_or_before="2005-01-01",
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["99.0"]
    assert [x["BMI_date_measured"] for x in results] == ["2001-10-01"]


def test_no_bmi_when_old_date():
    session = make_session()

    bmi_code = "22K.."

    patient = Patient(DateOfBirth="1950-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=bmi_code, NumericValue=99, ConsultationDate="1994-12-31")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            on_or_after="1995-01-01",
            on_or_before="2005-01-01",
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["0.0"]
    assert [x["BMI_date_measured"] for x in results] == [""]


def test_no_bmi_when_measurements_of_child():
    session = make_session()

    bmi_code = "22K.."

    patient = Patient(DateOfBirth="2000-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=bmi_code, NumericValue=99, ConsultationDate="2001-01-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            on_or_after="1995-01-01",
            on_or_before="2005-01-01",
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["0.0"]
    assert [x["BMI_date_measured"] for x in results] == [""]


def test_no_bmi_when_measurement_after_reference_date():
    session = make_session()

    bmi_code = "22K.."

    patient = Patient(DateOfBirth="1900-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=bmi_code, NumericValue=99, ConsultationDate="2001-01-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            on_or_after="1990-01-01",
            on_or_before="2000-01-01",
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["0.0"]
    assert [x["BMI_date_measured"] for x in results] == [""]


def test_bmi_when_only_some_measurements_of_child():
    session = make_session()

    bmi_code = "22K.."
    weight_code = "X76C7"
    height_code = "XM01E"

    patient = Patient(DateOfBirth="1990-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=bmi_code, NumericValue=99, ConsultationDate="1995-01-01")
    )
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=weight_code, NumericValue=50, ConsultationDate="2010-01-01")
    )
    patient.CodedEvents.append(
        CodedEvent(CTV3Code=height_code, NumericValue=10, ConsultationDate="2010-01-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        BMI=patients.most_recent_bmi(
            on_or_after="2005-01-01",
            on_or_before="2015-01-01",
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [x["BMI"] for x in results] == ["0.5"]
    assert [x["BMI_date_measured"] for x in results] == ["2010-01-01"]


def test_mean_recorded_value():
    code = "2469."
    session = make_session()
    patient = Patient()
    values = [
        ("2020-02-10", 90),
        ("2020-02-10", 100),
        ("2020-02-10", 98),
        # This day is outside period and should be ignored
        ("2020-04-01", 110),
    ]
    for date, value in values:
        patient.CodedEvents.append(
            CodedEvent(CTV3Code=code, NumericValue=value, ConsultationDate=date)
        )
    patient_with_old_reading = Patient()
    patient_with_old_reading.CodedEvents.append(
        CodedEvent(CTV3Code=code, NumericValue=100, ConsultationDate="2010-01-01")
    )
    patient_with_no_reading = Patient()
    session.add_all([patient, patient_with_old_reading, patient_with_no_reading])
    session.commit()
    study = StudyDefinition(
        population=patients.all(),
        bp_systolic=patients.mean_recorded_value(
            codelist([code], system="ctv3"),
            on_most_recent_day_of_measurement=True,
            between=["2018-01-01", "2020-03-01"],
            include_measurement_date=True,
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    results = [(i["bp_systolic"], i["bp_systolic_date_measured"]) for i in results]
    assert results == [("96.0", "2020-02-10"), ("0.0", ""), ("0.0", "")]


def test_patient_random_sample():
    session = make_session()
    sample_size = 1000
    for _ in range(sample_size):
        patient = Patient()
        session.add(patient)
    session.commit()

    study = StudyDefinition(population=patients.random_sample(percent=20))
    results = study.to_dicts()
    # The method is approximate!
    expected = sample_size * 0.2
    assert abs(len(results) - expected) < (expected * 0.1)


def test_patients_satisfying():
    condition_code = "ASTHMA"
    session = make_session()
    patient_1 = Patient(DateOfBirth="1940-01-01", Sex="M")
    patient_2 = Patient(DateOfBirth="1940-01-01", Sex="F")
    patient_3 = Patient(DateOfBirth="1990-01-01", Sex="M")
    patient_4 = Patient(DateOfBirth="1940-01-01", Sex="F")
    patient_4.CodedEvents.append(
        CodedEvent(CTV3Code=condition_code, ConsultationDate="2010-01-01")
    )
    session.add_all([patient_1, patient_2, patient_3, patient_4])
    session.commit()
    study = StudyDefinition(
        population=patients.all(),
        sex=patients.sex(),
        age=patients.age_as_of("2020-01-01"),
        has_asthma=patients.with_these_clinical_events(
            codelist([condition_code], "ctv3")
        ),
        at_risk=patients.satisfying("(age > 70 AND sex = 'M') OR has_asthma"),
    )
    results = study.to_dicts()
    assert [i["at_risk"] for i in results] == ["1", "0", "0", "1"]


def test_patients_satisfying_with_hidden_columns():
    condition_code = "ASTHMA"
    condition_code2 = "COPD"
    session = make_session()
    patient_1 = Patient(DateOfBirth="1940-01-01", Sex="M")
    patient_2 = Patient(DateOfBirth="1940-01-01", Sex="F")
    patient_3 = Patient(DateOfBirth="1990-01-01", Sex="M")
    patient_4 = Patient(DateOfBirth="1940-01-01", Sex="F")
    patient_4.CodedEvents.append(
        CodedEvent(CTV3Code=condition_code, ConsultationDate="2010-01-01")
    )
    patient_5 = Patient(DateOfBirth="1940-01-01", Sex="F")
    patient_5.CodedEvents.append(
        CodedEvent(CTV3Code=condition_code, ConsultationDate="2010-01-01")
    )
    patient_5.CodedEvents.append(
        CodedEvent(CTV3Code=condition_code2, ConsultationDate="2010-01-01")
    )
    session.add_all([patient_1, patient_2, patient_3, patient_4, patient_5])
    session.commit()
    study = StudyDefinition(
        population=patients.all(),
        sex=patients.sex(),
        age=patients.age_as_of("2020-01-01"),
        at_risk=patients.satisfying(
            """
            (age > 70 AND sex = "M")
            OR
            (has_asthma AND NOT copd)
            """,
            has_asthma=patients.with_these_clinical_events(
                codelist([condition_code], "ctv3")
            ),
            copd=patients.with_these_clinical_events(
                codelist([condition_code2], "ctv3")
            ),
        ),
    )
    results = study.to_dicts()
    assert [i["at_risk"] for i in results] == ["1", "0", "0", "1", "0"]
    assert "has_asthma" not in results[0].keys()


def test_patients_categorised_as():
    session = make_session()
    session.add_all(
        [
            Patient(
                Sex="M",
                CodedEvents=[
                    CodedEvent(CTV3Code="foo1", ConsultationDate="2000-01-01")
                ],
            ),
            Patient(
                Sex="F",
                CodedEvents=[
                    CodedEvent(CTV3Code="foo2", ConsultationDate="2000-01-01"),
                    CodedEvent(CTV3Code="bar1", ConsultationDate="2000-01-01"),
                ],
            ),
            Patient(
                Sex="M",
                CodedEvents=[
                    CodedEvent(CTV3Code="foo2", ConsultationDate="2000-01-01")
                ],
            ),
            Patient(
                Sex="F",
                CodedEvents=[
                    CodedEvent(CTV3Code="foo3", ConsultationDate="2000-01-01")
                ],
            ),
        ]
    )
    session.commit()
    foo_codes = codelist([("foo1", "A"), ("foo2", "B"), ("foo3", "C")], "ctv3")
    bar_codes = codelist(["bar1"], "ctv3")
    study = StudyDefinition(
        population=patients.all(),
        category=patients.categorised_as(
            {
                "W": "foo_category = 'B' AND female_with_bar",
                "X": "sex = 'F' AND (foo_category = 'B' OR foo_category = 'C')",
                "Y": "sex = 'M' AND foo_category = 'A'",
                "Z": "DEFAULT",
            },
            sex=patients.sex(),
            foo_category=patients.with_these_clinical_events(
                foo_codes, returning="category", find_last_match_in_period=True
            ),
            female_with_bar=patients.satisfying(
                "has_bar AND sex = 'F'",
                has_bar=patients.with_these_clinical_events(bar_codes),
            ),
        ),
    )
    results = study.to_dicts()
    assert [x["category"] for x in results] == ["Y", "W", "Z", "X"]
    # Assert that internal columns do not appear
    assert "foo_category" not in results[0].keys()
    assert "female_with_bar" not in results[0].keys()
    assert "has_bar" not in results[0].keys()


def test_patients_registered_practice_as_of():
    session = make_session()
    org_1 = Organisation(
        STPCode="123", MSOACode="E0201", Region="East of England", Organisation_ID=1
    )
    org_2 = Organisation(
        STPCode="456", MSOACode="E0202", Region="Midlands", Organisation_ID=2
    )
    org_3 = Organisation(
        STPCode="789", MSOACode="E0203", Region="London", Organisation_ID=3
    )
    org_4 = Organisation(
        STPCode="910", MSOACode="E0204", Region="North West", Organisation_ID=4
    )
    patient = Patient()
    patient.RegistrationHistory.append(
        RegistrationHistory(
            StartDate="1990-01-01", EndDate="2018-01-01", Organisation=org_1
        )
    )
    # We deliberately create overlapping registration periods so we can check
    # that we handle these correctly
    patient.RegistrationHistory.append(
        RegistrationHistory(
            StartDate="2018-01-01", EndDate="2022-01-01", Organisation=org_2
        )
    )
    patient.RegistrationHistory.append(
        RegistrationHistory(
            StartDate="2019-09-01", EndDate="2020-05-01", Organisation=org_3
        )
    )
    patient.RegistrationHistory.append(
        RegistrationHistory(
            StartDate="2022-01-01", EndDate="9999-12-31", Organisation=org_4
        )
    )
    patient_2 = Patient()
    patient_2.RegistrationHistory.append(
        RegistrationHistory(
            StartDate="2010-01-01", EndDate="9999-12-31", Organisation=org_1
        )
    )
    patient_3 = Patient()
    patient_3.RegistrationHistory.append(
        RegistrationHistory(StartDate="2010-01-01", EndDate="9999-12-31")
    )
    session.add_all([patient, patient_2, patient_3])
    session.commit()
    study = StudyDefinition(
        population=patients.all(),
        stp=patients.registered_practice_as_of("2020-01-01", returning="stp_code"),
        msoa=patients.registered_practice_as_of("2020-01-01", returning="msoa_code"),
        region=patients.registered_practice_as_of(
            "2020-01-01", returning="nhse_region_name"
        ),
        pseudo_id=patients.registered_practice_as_of(
            "2020-01-01", returning="pseudo_id"
        ),
    )
    results = study.to_dicts()
    assert [i["stp"] for i in results] == ["789", "123", ""]
    assert [i["msoa"] for i in results] == ["E0203", "E0201", ""]
    assert [i["region"] for i in results] == ["London", "East of England", ""]
    assert [i["pseudo_id"] for i in results] == ["3", "1", "0"]


def test_patients_address_as_of():
    session = make_session()
    patient = Patient()
    patient.Addresses.append(
        PatientAddress(
            StartDate="1990-01-01",
            EndDate="2018-01-01",
            ImdRankRounded=100,
            RuralUrbanClassificationCode=1,
        )
    )
    # We deliberately create overlapping address periods here to check that we
    # handle these correctly
    patient.Addresses.append(
        PatientAddress(
            StartDate="2018-01-01",
            EndDate="2020-02-01",
            ImdRankRounded=200,
            RuralUrbanClassificationCode=1,
        )
    )
    patient.Addresses.append(
        PatientAddress(
            StartDate="2019-01-01",
            EndDate="2022-01-01",
            ImdRankRounded=300,
            RuralUrbanClassificationCode=2,
        )
    )
    patient.Addresses.append(
        PatientAddress(
            StartDate="2022-01-01",
            EndDate="9999-12-31",
            ImdRankRounded=500,
            RuralUrbanClassificationCode=3,
        )
    )
    patient_no_address = Patient()
    patient_only_old_address = Patient()
    patient_only_old_address.Addresses.append(
        PatientAddress(
            StartDate="2010-01-01",
            EndDate="2015-01-01",
            ImdRankRounded=100,
            RuralUrbanClassificationCode=1,
        )
    )
    session.add_all([patient, patient_no_address, patient_only_old_address])
    session.commit()
    study = StudyDefinition(
        population=patients.all(),
        imd=patients.address_as_of(
            "2020-01-01",
            returning="index_of_multiple_deprivation",
            round_to_nearest=100,
        ),
        rural_urban=patients.address_as_of(
            "2020-01-01", returning="rural_urban_classification"
        ),
    )
    results = study.to_dicts()
    assert [i["imd"] for i in results] == ["300", "0", "0"]
    assert [i["rural_urban"] for i in results] == ["2", "0", "0"]


def test_patients_admitted_to_icu():
    session = make_session()
    patient_1 = Patient()
    patient_1.ICNARC.append(
        ICNARC(
            IcuAdmissionDateTime="2020-03-01",
            OriginalIcuAdmissionDate="2020-03-01",
            BasicDays_RespiratorySupport=2,
            AdvancedDays_RespiratorySupport=2,
            Ventilator=0,
        )
    )
    patient_2 = Patient()
    patient_2.ICNARC.append(
        ICNARC(
            IcuAdmissionDateTime="2020-03-01",
            OriginalIcuAdmissionDate="2020-02-01",
            BasicDays_RespiratorySupport=1,
            AdvancedDays_RespiratorySupport=0,
            Ventilator=1,
        )
    )
    patient_3 = Patient()
    patient_3.ICNARC.append(
        ICNARC(
            IcuAdmissionDateTime="2020-03-01",
            OriginalIcuAdmissionDate="2020-02-01",
            BasicDays_RespiratorySupport=0,
            AdvancedDays_RespiratorySupport=0,
            Ventilator=0,
        )
    )
    patient_4 = Patient()
    patient_4.ICNARC.append(
        ICNARC(
            IcuAdmissionDateTime="2020-01-01",
            OriginalIcuAdmissionDate="2020-01-01",
            BasicDays_RespiratorySupport=1,
            AdvancedDays_RespiratorySupport=0,
            Ventilator=1,
        )
    )
    patient_5 = Patient()
    patient_5.ICNARC.append(
        ICNARC(
            IcuAdmissionDateTime="2020-03-01",
            OriginalIcuAdmissionDate=None,
            BasicDays_RespiratorySupport=1,
            AdvancedDays_RespiratorySupport=0,
            Ventilator=1,
        )
    )
    patient_5.ICNARC.append(
        ICNARC(
            IcuAdmissionDateTime="2020-04-01",
            OriginalIcuAdmissionDate=None,
            BasicDays_RespiratorySupport=0,
            AdvancedDays_RespiratorySupport=0,
            Ventilator=1,
        )
    )
    session.add_all([patient_1, patient_2, patient_3, patient_4, patient_5])
    session.commit()

    study = StudyDefinition(
        population=patients.all(),
        icu=patients.admitted_to_icu(
            on_or_after="2020-02-01",
            include_day=True,
            returning="date_admitted",
            find_first_match_in_period=True,
        ),
    )
    results = study.to_dicts()

    assert [i["icu"] for i in results] == [
        "2020-03-01",
        "2020-02-01",
        "",
        "",
        "2020-03-01",
    ]

    study = StudyDefinition(
        population=patients.all(),
        icu=patients.admitted_to_icu(
            on_or_after="2020-02-01",
            include_day=True,
            returning="date_admitted",
            find_last_match_in_period=True,
        ),
    )
    results = study.to_dicts()

    assert [i["icu"] for i in results] == [
        "2020-03-01",
        "2020-02-01",
        "",
        "",
        "2020-04-01",
    ]

    study = StudyDefinition(
        population=patients.all(),
        icu=patients.admitted_to_icu(on_or_after="2020-02-01", returning="binary_flag"),
    )
    results = study.to_dicts()

    assert [i["icu"] for i in results] == ["1", "1", "0", "0", "1"]


def test_patients_with_these_codes_on_death_certificate():
    code = "COVID"
    session = make_session()
    session.add_all(
        [
            # Not dead
            Patient(),
            # Died after date cutoff
            Patient(ONSDeath=[ONSDeaths(dod="2021-01-01", icd10u=code)]),
            # Died of something else
            Patient(ONSDeath=[ONSDeaths(dod="2020-02-01", icd10u="MI")]),
            # Covid underlying cause
            Patient(ONSDeath=[ONSDeaths(dod="2020-02-01", icd10u=code)]),
            # Covid not underlying cause
            Patient(ONSDeath=[ONSDeaths(dod="2020-03-01", ICD10014=code)]),
        ]
    )
    session.commit()
    covid_codelist = codelist([code], system="icd10")
    study = StudyDefinition(
        population=patients.all(),
        died_of_covid=patients.with_these_codes_on_death_certificate(
            covid_codelist, on_or_before="2020-06-01", match_only_underlying_cause=True
        ),
        died_with_covid=patients.with_these_codes_on_death_certificate(
            covid_codelist, on_or_before="2020-06-01", match_only_underlying_cause=False
        ),
        date_died=patients.with_these_codes_on_death_certificate(
            covid_codelist,
            on_or_before="2020-06-01",
            match_only_underlying_cause=False,
            returning="date_of_death",
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [i["died_of_covid"] for i in results] == ["0", "0", "0", "1", "0"]
    assert [i["died_with_covid"] for i in results] == ["0", "0", "0", "1", "1"]
    assert [i["date_died"] for i in results] == ["", "", "", "2020-02-01", "2020-03-01"]


def test_patients_died_from_any_cause():
    session = make_session()
    session.add_all(
        [
            # Not dead
            Patient(),
            # Died after date cutoff
            Patient(ONSDeath=[ONSDeaths(dod="2021-01-01")]),
            # Died
            Patient(ONSDeath=[ONSDeaths(dod="2020-02-01")]),
        ]
    )
    session.commit()
    study = StudyDefinition(
        population=patients.all(),
        died=patients.died_from_any_cause(on_or_before="2020-06-01"),
        date_died=patients.died_from_any_cause(
            on_or_before="2020-06-01",
            returning="date_of_death",
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [i["died"] for i in results] == ["0", "0", "1"]
    assert [i["date_died"] for i in results] == ["", "", "2020-02-01"]


def test_patients_with_death_recorded_in_cpns():
    session = make_session()
    session.add_all(
        [
            # Not dead
            Patient(),
            # Died after date cutoff
            Patient(CPNS=[CPNS(DateOfDeath="2021-01-01")]),
            # Patient should be included
            Patient(CPNS=[CPNS(DateOfDeath="2020-02-01")]),
            # Patient has multiple entries but with the same date of death so
            # should be handled correctly
            Patient(
                CPNS=[CPNS(DateOfDeath="2020-03-01"), CPNS(DateOfDeath="2020-03-01")]
            ),
        ]
    )
    session.commit()
    study = StudyDefinition(
        population=patients.all(),
        cpns_death=patients.with_death_recorded_in_cpns(on_or_before="2020-06-01"),
        cpns_death_date=patients.with_death_recorded_in_cpns(
            on_or_before="2020-06-01",
            returning="date_of_death",
            include_month=True,
            include_day=True,
        ),
    )
    results = study.to_dicts()
    assert [i["cpns_death"] for i in results] == ["0", "0", "1", "1"]
    assert [i["cpns_death_date"] for i in results] == [
        "",
        "",
        "2020-02-01",
        "2020-03-01",
    ]


def test_patients_with_death_recorded_in_cpns_raises_error_on_bad_data():
    session = make_session()
    session.add_all(
        # Create a patient with duplicate CPNS entries recording an
        # inconsistent date of death
        [Patient(CPNS=[CPNS(DateOfDeath="2020-03-01"), CPNS(DateOfDeath="2020-02-01")])]
    )
    session.commit()
    study = StudyDefinition(
        population=patients.all(), cpns_death=patients.with_death_recorded_in_cpns()
    )
    with pytest.raises(Exception):
        study.to_dicts()


def test_filter_codes_by_category():
    codes = codelist([("1", "A"), ("2", "B"), ("3", "A"), ("4", "C")], "ctv3")
    filtered = filter_codes_by_category(codes, include=["B", "C"])
    assert filtered.system == codes.system
    assert filtered == [("2", "B"), ("4", "C")]


def test_to_sql_passes():
    session = make_session()
    patient = Patient(DateOfBirth="1950-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code="XYZ", NumericValue=50, ConsultationDate="2002-06-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.with_these_clinical_events(codelist(["XYZ"], "ctv3"))
    )
    sql = "SET NOCOUNT ON; "  # don't output count after table output
    sql += study.to_sql()
    db_dict = study.get_db_dict()
    cmd = [
        "sqlcmd",
        "-S",
        db_dict["hostname"] + "," + str(db_dict["port"]),
        "-d",
        db_dict["database"],
        "-U",
        db_dict["username"],
        "-P",
        db_dict["password"],
        "-Q",
        sql,
        "-W",  # strip whitespace
    ]
    result = subprocess.run(
        cmd, capture_output=True, check=True, encoding="utf8"
    ).stdout
    patient_id = result.splitlines()[-1]
    assert patient_id == str(patient.Patient_ID)


def test_duplicate_id_checking():
    study = StudyDefinition(population=patients.all())
    # A bit of a hack: overwrite the queries we're going to run with a query which
    # deliberately returns duplicate values
    study.queries = [
        (
            "dummy_query",
            """
            SELECT * FROM (
              VALUES
                (1,1),
                (2,2),
                (3,3),
                (1,4)
            ) t (patient_id, foo)
            """,
        )
    ]
    with pytest.raises(RuntimeError):
        study.to_dicts()
    with pytest.raises(RuntimeError):
        with tempfile.NamedTemporaryFile(mode="w+") as f:
            study.to_csv(f.name)


def test_sqlcmd_and_odbc_outputs_match():
    session = make_session()
    patient = Patient(DateOfBirth="1950-01-01")
    patient.CodedEvents.append(
        CodedEvent(CTV3Code="XYZ", NumericValue=50, ConsultationDate="2002-06-01")
    )
    session.add(patient)
    session.commit()

    study = StudyDefinition(
        population=patients.with_these_clinical_events(codelist(["XYZ"], "ctv3"))
    )
    with tempfile.NamedTemporaryFile() as input_csv_odbc, tempfile.NamedTemporaryFile() as input_csv_sqlcmd:
        # windows line endings
        study.to_csv(input_csv_odbc.name, with_sqlcmd=False)
        # unix line endings
        study.to_csv(input_csv_sqlcmd.name, with_sqlcmd=True)
        assert filecmp.cmp(input_csv_odbc.name, input_csv_sqlcmd.name, shallow=False)


def test_column_name_clashes_produce_errors():
    with pytest.raises(ValueError):
        StudyDefinition(
            population=patients.all(),
            age=patients.age_as_of("2020-01-01"),
            status=patients.satisfying(
                "age > 70 AND sex = 'M'",
                sex=patients.sex(),
                age=patients.age_as_of("2010-01-01"),
            ),
        )


def test_recursive_definitions_produce_errors():
    with pytest.raises(ValueError):
        StudyDefinition(
            population=patients.all(),
            this=patients.satisfying("that = 1"),
            that=patients.satisfying("this = 1"),
        )

## Pandas import specification tests


def _converters_to_names(kwargs_dict):
    converters = kwargs_dict.pop("converters")
    converters_with_names = {}
    if converters:
        for k, v in converters.items():
            converters_with_names[k] = v.__name__
    kwargs_dict["converters"] = converters_with_names
    return kwargs_dict


def test_age_dtype_generation():
    study = StudyDefinition(
        # This line defines the study population
        population=patients.all(),
        age=patients.age_as_of("2020-02-01"),
    )
    result = study.pandas_csv_args
    assert result == {"dtype": {"age": "int"}, "converters": {}, "parse_dates": []}


def test_address_dtype_generation():
    study = StudyDefinition(
        # This line defines the study population
        population=patients.all(),
        rural_urban=patients.address_as_of(
            "2020-02-01", returning="rural_urban_classification"
        ),
    )
    result = study.pandas_csv_args
    assert result == {
        "converters": {},
        "dtype": {"rural_urban": "category"},
        "parse_dates": [],
    }


def test_sex_dtype_generation():
    study = StudyDefinition(population=patients.all(), sex=patients.sex())
    result = study.pandas_csv_args
    assert result == {"dtype": {"sex": "category"}, "converters": {}, "parse_dates": []}


def test_clinical_events_with_date_dtype_generation():
    test_codelist = codelist(["X"], system="ctv3")
    study = StudyDefinition(
        population=patients.all(),
        diabetes=patients.with_these_clinical_events(
            test_codelist, return_first_date_in_period=True, include_month=True
        ),
    )

    result = _converters_to_names(study.pandas_csv_args)
    assert result == {
        "converters": {"diabetes": "add_day_to_date"},
        "dtype": {},
        "parse_dates": ["diabetes"],
    }


def test_clinical_events_with_year_date_dtype_generation():
    test_codelist = codelist(["X"], system="ctv3")
    study = StudyDefinition(
        population=patients.all(),
        diabetes=patients.with_these_clinical_events(test_codelist, returning="date"),
    )
    result = _converters_to_names(study.pandas_csv_args)
    assert result == {
        "converters": {"diabetes": "add_month_and_day_to_date"},
        "dtype": {},
        "parse_dates": ["diabetes"],
    }


def test_categorical_clinical_events_with_date_dtype_generation():
    categorised_codelist = codelist([("X", "Y")], system="ctv3")
    categorised_codelist.has_categories = True
    study = StudyDefinition(
        population=patients.all(),
        ethnicity=patients.with_these_clinical_events(
            categorised_codelist,
            returning="category",
            find_last_match_in_period=True,
            include_date_of_match=True,
        ),
    )

    result = _converters_to_names(study.pandas_csv_args)
    assert result == {
        "converters": {"ethnicity_date": "add_month_and_day_to_date"},
        "dtype": {"ethnicity": "category"},
        "parse_dates": ["ethnicity_date"],
    }


def test_categorical_clinical_events_without_date_dtype_generation():
    categorised_codelist = codelist([("X", "Y")], system="ctv3")
    categorised_codelist.has_categories = True
    study = StudyDefinition(
        population=patients.all(),
        ethnicity=patients.with_these_clinical_events(
            categorised_codelist,
            returning="category",
            find_last_match_in_period=True,
            include_date_of_match=False,
        ),
    )

    result = study.pandas_csv_args
    assert result == {
        "converters": {},
        "dtype": {"ethnicity": "category"},
        "parse_dates": [],
    }


def test_bmi_dtype_generation():
    categorised_codelist = codelist([("X", "Y")], system="ctv3")
    categorised_codelist.has_categories = True
    study = StudyDefinition(
        population=patients.all(),
        bmi=patients.most_recent_bmi(
            on_or_after="2010-02-01",
            minimum_age_at_measurement=16,
            include_measurement_date=True,
            include_month=True,
        ),
    )

    result = _converters_to_names(study.pandas_csv_args)
    assert result == {
        "converters": {"bmi_date_measured": "add_day_to_date"},
        "dtype": {"bmi": "float"},
        "parse_dates": ["bmi_date_measured"],
    }


def test_clinical_events_numeric_value_dtype_generation():
    test_codelist = codelist(["X"], system="ctv3")
    study = StudyDefinition(
        population=patients.all(),
        creatinine=patients.with_these_clinical_events(
            test_codelist,
            find_last_match_in_period=True,
            on_or_before="2020-02-01",
            returning="numeric_value",
            include_date_of_match=True,
            include_month=True,
        ),
    )
    result = _converters_to_names(study.pandas_csv_args)
    assert result == {
        "converters": {"creatinine_date": "add_day_to_date"},
        "dtype": {"creatinine": "float"},
        "parse_dates": ["creatinine_date"],
    }


def test_mean_recorded_value_dtype_generation():
    test_codelist = codelist(["X"], system="ctv3")
    study = StudyDefinition(
        population=patients.all(),
        bp_sys=patients.mean_recorded_value(
            test_codelist,
            on_most_recent_day_of_measurement=True,
            on_or_before="2020-02-01",
            include_measurement_date=True,
            include_month=True,
        ),
    )
    result = _converters_to_names(study.pandas_csv_args)
    assert result == {
        "converters": {"bp_sys_date_measured": "add_day_to_date"},
        "dtype": {"bp_sys": "float"},
        "parse_dates": ["bp_sys_date_measured"],
    }

def test_using_expression_in_population_definition():
    session = make_session()
    session.add_all(
        [
            Patient(
                Sex="M",
                DateOfBirth="1970-01-01",
                CodedEvents=[
                    CodedEvent(CTV3Code="foo1", ConsultationDate="2000-01-01")
                ],
            ),
            Patient(Sex="M", DateOfBirth="1975-01-01"),
            Patient(
                Sex="F",
                DateOfBirth="1980-01-01",
                CodedEvents=[
                    CodedEvent(CTV3Code="foo1", ConsultationDate="2000-01-01")
                ],
            ),
            Patient(Sex="F", DateOfBirth="1985-01-01"),
        ]
    )
    session.commit()
    study = StudyDefinition(
        population=patients.satisfying(
            "has_foo_code AND sex = 'M'",
            has_foo_code=patients.with_these_clinical_events(
                codelist(["foo1"], "ctv3")
            ),
            sex=patients.sex(),
        ),
        age=patients.age_as_of("2020-01-01"),
    )
    results = study.to_dicts()
    assert results[0].keys() == {"patient_id", "age"}
    assert [i["age"] for i in results] == ["50"]
    

def test_quote():
    with pytest.raises(ValueError):
        quote("foo!")
    assert quote("2012-02-01") == "'20120201'"
    assert quote("2012") == "'2012'"
    assert quote(2012) == "2012"
    assert quote(0.1) == "0.1"
    assert quote("foo") == "'foo'"

