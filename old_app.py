from flask import Flask, request, jsonify, render_template_string
import time
import urllib3
import requests
import re
import json
import random
import logging

app = Flask(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# TODO
# - Display only a few randomised images (e.g. 3-6)
# - Templates

# Define the proxy
proxies = {
}

# Create a session to handle cookies
session = requests.Session()
session.proxies = proxies

giftig_full = {"s":"spiselig", "smm":"spiselig med merknad", "im":"ikke matsopp", "g":"giftig", "mg":"meget giftig"}

def hex_encode(search_term):
    return '%'.join(f"{ord(c):02x}" for c in search_term)

def get_request_verification_token():
    response = session.get(
        'https://artsobservasjoner.no/ViewSighting/SearchSighting',
        headers={
            'Host': 'artsobservasjoner.no',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Dnt': '1',
            'Referer': 'https://artsobservasjoner.no/',
            'Upgrade-Insecure-Requests': '1'
        },
        verify=False
    )
    token = re.search(r'__RequestVerificationToken" type="hidden" value="(.*?)"', response.text)
    return token.group(1) if token else None

def get_taxon_id(search):
    print(f"--> Searching taxonid for {search}")
    response = session.get(
        f"https://artsobservasjoner.no/Taxon/PickerSearch?search={search}&returnformat=html&onlyReportable=false&dontIncludeSubSpecies=true&speciesGroup=-1&language=4",
        headers={
            'Host': 'artsobservasjoner.no',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0',
            'Accept': 'text/html, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Dnt': '1',
            'Referer': 'https://artsobservasjoner.no/ViewSighting/SearchSighting'
        },
        verify=False
    )
    json_match = re.search(r'itemjson">(.*?)</span>', response.text)
    if json_match:
        json_data = json_match.group(1)
        #print(json_data)

        taxon_data = json.loads(json_data)
        #print(taxon_data)
        taxonid = taxon_data.get("taxonid")
    return taxonid if taxonid else None

def perform_search(token, taxon_id):
    data = {
        "__RequestVerificationToken": token,
        "SearchViewModel.CanViewProtectedSightings": "False",
        "SearchViewModel.HasGrantedTaxon": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Reporter": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.TransferredOldUserId": "",
        "StoredSearchCriterias.Id": "0",
        "SearchViewModel.Taxons_Selector_Value": "",
        "SearchViewModel.Taxons_speciesgroupid": "4",
        "SearchViewModel.Taxons_Name": "",
        "SearchViewModel.Taxons_Selector_Text": "",
        "SearchViewModel.Taxons_LanguageId": "4",
        "SearchViewModel.Taxons_ScopeId": "-1",
        "SearchViewModel.Taxons": f"{taxon_id},",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.IncludeChildTaxon": "true",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.UnsureDeterminationFilter": "20",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowUnsureDeterminationCriteria": "True",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.UnspontaneousFilter": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowUnspontaneousCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.RedLists_Select": "-1",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.RedLists": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowRedListCriteria": "True",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.LastNumberOfDays": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.FromDate": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ToDate": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.UsePeriodForAllYears": "false",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowDateCriteria": "True",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.FromYear": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ToYear": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowYearCriteria": "True",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.FromMonth": "-1",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ToMonth": "-1",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowMonthCriteria": "True",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.FromRegisterDate": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ToRegisterDate": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowRegisterDateCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.BoundingGeometryByWkt": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Sites_Selector_Value": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Sites_Selector_Text": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Sites": "",
        "SearchViewModel.SelectableCounties.SelectedItems_Select": "-1",
        "SearchViewModel.SelectableCounties.SelectedItems": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowCountyCriteria": "True",
        "SearchViewModel.SelectableMunicipalities.SelectedItems_Select": "-1",
        "SearchViewModel.SelectableMunicipalities.SelectedItems": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowMunicipalityCriteria": "True",
        "SearchViewModel.OtherAreas_Selector_Value": "",
        "SearchViewModel.OtherAreas_Selector_Text": "",
        "SearchViewModel.OtherAreas": "",
        "SearchViewModel.SelectableBirdreportArea.SelectedItems_Select": "-1",
        "SearchViewModel.SelectableBirdreportArea.SelectedItems": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowBirdreportAreaCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ImageFilter": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.RuleViolationFilter": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.IncludeValidationRejected": "false",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ValidationStatuses_Select": "-1",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ValidationStatuses": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.IncludeEditedSightings": "false",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowIncludeEditedSightingsCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.RegionalSightingStates_Select": "-1",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.RegionalSightingStates": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SightingsWithComments": "false",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.NoteOfInterest": "false",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowNoteOfInterestCriteria": "True",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.QuantityOperatorType": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Quantity": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowQuantityCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Genders": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowGenderCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Stages_Select": "0",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Stages": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowStageCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Activities": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowActivityCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ActivityCategories": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowActivityCategoryCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.DiscoveryMethods": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowDiscoveryMethodCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Project": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Project_Name": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowProjectCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.LengthOperatorType": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowLengthCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.WeightOperatorType": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowWeightCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.DepthOperatorType": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Depth": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowDepthCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.AltitudeOperatorType": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Altitude": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowDepthCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SecondHandInformation": "false",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSecondHandInformationCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SightingSpeciesCollectionItemLabel": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSightingSpeciesCollectionItemLabelCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.CollectionDescriptionText": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSightingSpeciesCollectionItemLabelCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.PrintedLabelFilter": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSightingSpeciesCollectionItemLabelCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SpeciesCollection": "-1",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSpeciesCollectionCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SpeciesCollector": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SpeciesCollector_Name": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSpeciesCollectorCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.NotRecoveredFilter": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowNotRecoveredCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.NotPresentFilter": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowNotPresentCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.BiotopeNiN2": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.BiotopeNiN2_Name": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowBiotopeCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.BiotopeText": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowBiotopeCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SubstrateSpecies": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SubstrateSpecies_speciesgroupid": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SubstrateSpecies_Name": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SubstrateSpecies_LanguageId": "4",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SubstrateSpecies_ScopeId": "-1",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSubstrateSpeciesCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SubstrateSpecieText": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSubstrateSpeciesCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Substrate": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.Substrate_Name": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSubstrateCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.QuantityOfSubstrateOperatorType": "10",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.QuantityOfSubstrate": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSubstrateCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.SubstrateText": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowSubstrateCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.AssessmentSightingsFilter": "40",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowAssessmentSightingsCriteria": "True",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.PublicCommentText": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowCommentCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.DeterminerName_Id": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.DeterminerName": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowDeterminerCriteria": "False",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ConfirmatorName_Id": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ConfirmatorName": "",
        "SightingDatasourceFilter": "",
        "SearchViewModel.SightingDatasourceType": "",
        "SearchViewModel.ApiSecurity": "",
        "SearchViewModel.StoredSearchCriterias.SearchCriterias.ShowDatasourceFilter": "False"
    }
    
    response = session.post(
        'https://artsobservasjoner.no/ViewSighting/ViewSightingAsGallery',
        headers={
            'Host': 'artsobservasjoner.no',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://artsobservasjoner.no/ViewSighting/SearchSighting'
        },
        data=data,
        verify=False
    )

    return response

@app.route('/', methods=['GET','POST'])
@app.route('/guess', methods=['GET','POST'])
@app.route('/search', methods=['GET'])
def search():
    random.seed(int(time.time() * 1000))
    feedback = None
    # Select a random search term
#    with open('pensum.txt', 'r') as file:
#        search_terms = file.readlines()
    pensum_data = json.load(open('pensum.json', 'r'))
    art = random.choice(pensum_data)
    search_term = art.get("norsknavn")
    normstatus = ''.join(word[0] for word in art.get("normstatus").split()) # Just get the code (e.g., "meget giftig" -> "mg")
    merknad = art.get("kommentar")

    if request.path == '/search':
        search_term = request.args.get('q')
    else:
      user_guess = request.form.get('user_guess')
      answer = request.form.get('answer')
      normstatus_answer = request.form.get('normstatus_answer')

      # Check the user's guess
      if user_guess and answer and normstatus_answer:
          try:
              user_art_guess, user_normstatus_guess = user_guess.split(",")
              if user_art_guess.strip().lower() == answer.lower():
                  feedback = "<font color=green>Riktig art!</font> "
              else:
                  feedback = f"<font color=red>Feil art. Riktig art er <a href=\"/old/search?q={(answer)}\">{answer}</a>.</font> "

              if user_normstatus_guess.strip().lower() == normstatus_answer.lower():
                  feedback += "<font color=green>Riktig normlistestatus!</font>"
              else:
                  feedback += f"<font color=red>Feil normelistestatus. Riktig normlistestatus er {normstatus_answer} ({giftig_full[normstatus_answer]}).</font>"
          except:
              feedback = "<font color=blue>Svaret må være i form: <i>norsknavn,normlistestatus</i> hvor normlistestatus er en av <i>s,smm,im,g,mg (spiselig, spiselig med merknad, ikke matsopp, giftig, meget giftig)</i></font>"

          print(f"--> Guess {user_guess}, answer {answer}")

    #print(session.cookies.get_dict())

    for retry in range(0,5):
        taxon_id = None
        try:
            token = get_request_verification_token()
            if not token:
                return jsonify({"error": "Failed to retrieve token"}), 500

            taxon_id = get_taxon_id(search_term)
        except:
            print(f"Failed to retrieve taxon ID with token {token}")
        if retry == 4 and taxon_id == None:
            return jsonify({"error": f"Failed to retrieve taxon ID with token {token}, press reload (Ctrl+R) to resubmit your answer and continue"}), 500
        if not taxon_id == None:
            break

    for retry in range(0,5):
        response = perform_search(token, taxon_id)
        if not response:
            print(f"Failed to perform search on {search_term} with taxonid {taxon_id} attempt {retry}")
        if retry == 4 and not response:
            return jsonify({"error": f"Failed to perform search on {search_term} with taxonid {taxon_id}, press Ctrl-R to resubmit your answer and continue"}), 500

    image_urls = re.findall(r'<img src="(.*?)"', response.text)
    image_urls = [f"https://artsobservasjoner.no{url}" for url in image_urls]
    if not request.path == '/search':
        image_urls = random.sample(image_urls, k=3)

    # Generate HTML response with the form
    if request.path == '/guess' or request.path == '/':
        html_response = '<html><head><title>Pensum soppquiz</title>'
        html_response += '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        html_response += '</head><body>'
        if feedback:
            html_response += f'<p>{feedback}</p>'
        html_response += '<form method="POST">'
        html_response += f'<input type="hidden" name="answer" value="{search_term}">'
        html_response += f'<input type="hidden" name="normstatus_answer" value="{normstatus}">'
        html_response += '<label for="user_guess">Angi art,normlistestatus (e.g., <i>giftsopp,g</i>):</label>'
        html_response += '<input type="text" name="user_guess" required autofocus>'
        html_response += '<input type="submit" value="OK">'
        html_response += '</form>'
    else:
        html_response = '<html><head><title>Pensum search</title></head><body>'
    html_response += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px;">'
    
    #for url in image_urls:
    #    html_response += f'<div><a href="{url.replace('_thumbnail', '_image')}" target=_blank><img src="{url}" style="width: 100%; height: auto;" /></a></div>'
    for url in image_urls:
        html_response += f'<div><a href="{url.replace('_thumbnail', '_image')}" target=_blank><img src="{url.replace('_thumbnail', '_image')}" style="width: 100%; height: auto;" /></a></div>'
    
    html_response += '</div><p>Bilder fra Artsobservasjoner.no. Contact donn@tuta.io</p></body></html>'
    
    return html_response
if __name__ == '__main__':
    app.run(debug=True)
