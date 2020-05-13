# Factors associated with COVID-19-related hospital death

This is the code and configuration for our paper, _OpenSAFELY: factors associated with
COVID-19-related hospital death in the linked electronic health records of 17 million adult
NHS patients_

* The paper is [here](https://www.medrxiv.org/content/10.1101/2020.05.06.20092999v1)
* Raw model outputs, including charts, crosstabs, etc, are in `released_analysis_results/`
* If you are interested in how we defined our covarates, take a look at the [study definition](analysis/study_definition.py); this is written in Python, but non-programmers should be able to understand what is going on there
* If you are interested in how we defined our code lists, look in the [codelists folder](./codelists/). A new tool
called OpenSafely Codelists was developed to allow codelists to be versioned and hosted online at [codelists.opensafely.org](http://codelists.opensafely.org)

# About the OpenSAFELY framework

The OpenSAFELY framework is a new secure analytics platform for
electronic health records research in the NHS.

Instead of requesting access for slices of patient data and
transporting them elsewhere for analysis, the framework supports
developing analytics against dummy data, and then running against the
real data *within the same infrastructure that the data is stored*.
Read more at [OpenSAFELY.org](https://opensafely.org).

All the software is Open Source; however, it's recently come to our
attention the code may include some commercial IP, so we have
temporarily removed it from Github until we address that.  We expect
the code to be published again in during the week commencing 18 May.
