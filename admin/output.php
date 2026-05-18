<?php

/*	Copyright Deakin University 2007,2008
 *	Written by Adam Zammit - adam.zammit@deakin.edu.au
 *	For the Deakin Computer Assisted Research Facility: http://www.deakin.edu.au/dcarf/
 *	
 *	This file is part of queXF
 *	
 *	queXF is free software; you can redistribute it and/or modify
 *	it under the terms of the GNU General Public License as published by
 *	the Free Software Foundation; either version 2 of the License, or
 *	(at your option) any later version.
 *	
 *	queXF is distributed in the hope that it will be useful,
 *	but WITHOUT ANY WARRANTY; without even the implied warranty of
 *	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *	GNU General Public License for more details.
 *	
 *	You should have received a copy of the GNU General Public License
 *	along with queXF; if not, write to the Free Software
 *	Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 *
 */


include_once("../config.inc.php");
include_once("../db.inc.php");
include ("../functions/functions.output.php");
include ("../functions/functions.xhtml.php");

if (isset($_GET['ddi']))
{
	export_ddi(intval($_GET['ddi']));
	exit();
}

if (isset($_GET['data']))
{
	outputdata(intval($_GET['data']));
	exit();
}

if (isset($_GET['csvlabel']))
{
	outputdatacsv(intval($_GET['csvlabel']),"",true);
	exit();
}

if (isset($_GET['csv']))
{
	outputdatacsv(intval($_GET['csv']));
	exit();
}

if (isset($_GET['csvmerged']))
{
	outputdatacsv(intval($_GET['csvmerged']),"",false,false,false,true);
	exit();
}

if (isset($_GET['banding']))
{
	export_banding(intval($_GET['banding']));
	exit();
}

if (isset($_GET['pspp']))
{
	export_pspp(intval($_GET['pspp']));
	exit();
}

xhtml_head(T_("Output data"),true,array("../css/table.css"));

$sql = "SELECT description, qid, quexf_pdf,
		CONCAT('<a href=\"?data=', qid, '\">" . T_("Data") . "</a>') as data,
		CONCAT('<a href=\"?ddi=', qid, '\">" . T_("DDI") . "</a>') as ddi,
		CONCAT('<a href=\"?csv=', qid, '\">" . T_("CSV") . "</a>') as csv,
		CONCAT('<a href=\"?csvmerged=', qid, '\">" . T_("CSV Merged") . "</a>') as csvmerged,
		CONCAT('<a href=\"?csvlabel=', qid, '\">" . T_("CSV Labelled") . "</a>') as csvlabel,
		CONCAT('<a href=\"?pspp=', qid, '\">" . T_("PSPP (SPSS)") . "</a>') as pspp,
		CONCAT('<a href=\"?banding=', qid, '\">" . T_("Banding XML") . "</a>') as banding
	FROM questionnaires
	ORDER BY qid DESC";


$qs = $db->GetAll($sql);

foreach ($qs as &$row) {
    // Display the button only if quexf_pdf is not NULL and not empty and have forms verified
	$sqlcount = "
		SELECT COUNT(fid) AS nbf
		FROM forms AS f
		WHERE f.qid = ". $row['qid'] ."
		AND done IN (1,3)
	";
	$nbrow = $db->GetAll($sqlcount);
    if (!is_null($row['quexf_pdf']) && $row['quexf_pdf'] !== '' && intval($nbrow[0]['nbf']) > 0) {
        $row['filledpdfzip'] =
            '<button class="download-filled-pdf-zip" data-qid="' .
            htmlspecialchars($row['qid']) .
            '">' .
            T_("ZIP of filled PDFs") .
            '</button>';
    } else {
        $row['filledpdfzip'] = '';
    }
}

xhtml_table($qs, array('description','data','ddi','csv','csvmerged','csvlabel','pspp','banding','filledpdfzip'),array(T_("Questionnaire"),T_("Data"),T_("DDI"),T_("CSV"),T_("CSV Merged"),T_("CSV Labelled"), T_("PSPP (SPSS)"), T_("Banding XML"), T_("ZIP of filled PDFs")));

?>
<style>
#zip-progress-overlay {
	position: fixed;
	inset: 0;
	background: rgba(0, 0, 0, 0.45);
	display: none;
	align-items: center;
	justify-content: center;
	z-index: 9999;
}

#zip-progress-box {
	background: #fff;
	padding: 24px 32px;
	border-radius: 8px;
	box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
	text-align: center;
	font-family: Arial, sans-serif;
	max-width: 420px;
}

#zip-progress-spinner {
	width: 38px;
	height: 38px;
	border: 4px solid #ddd;
	border-top-color: #2b6cb0;
	border-radius: 50%;
	animation: zip-spin 1s linear infinite;
	margin: 0 auto 16px auto;
}

@keyframes zip-spin {
	to {
		transform: rotate(360deg);
	}
}
</style>

<div id="zip-progress-overlay">
	<div id="zip-progress-box">
		<div id="zip-progress-spinner"></div>
		<strong>ZIP file generation in progress…</strong>
		<p>Please wait while the completed PDFs are being generated.</p>
	</div>
</div>

<script src="../js/prototype-1.6.0.2.js"></script> <!-- Ensure Prototype is included -->
<script type="text/javascript">
document.addEventListener("DOMContentLoaded", function () {
	var links = document.querySelectorAll(".download-filled-pdf-zip");
	links.forEach(function (link) {
		link.addEventListener("click", function (event) {
			event.preventDefault(); // Prevent the default link behavior
			var qid = this.getAttribute('data-qid');
			generateAndDownloadZip(qid);
		});
	});

	function generateAndDownloadZip(qid) {
		var overlay = document.getElementById("zip-progress-overlay");
		if (overlay) {
			overlay.style.display = "flex";
		}

		new Ajax.Request('generate_zip.php', {
			method: 'post',
			parameters: { qid: qid },
			onSuccess: function(response) {
				var jsonResponse = response.responseJSON;
				if (jsonResponse.success && jsonResponse.downloadUrl) {
					window.location.href = jsonResponse.downloadUrl; // Redirect to download
				} else {
					alert('Error generating the ZIP file:' + jsonResponse.message);
				}
				if (overlay) {
					overlay.style.display = "none";
				}
			},
			onFailure: function() {
				alert('An error has occurred. Please try again later.');
				if (overlay) {
					overlay.style.display = "none";
				}
			}
		});
	}
});
</script>
<?php

xhtml_foot();

?>
