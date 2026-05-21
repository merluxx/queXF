<?php
include_once("../config.inc.php");
include_once("../db.inc.php");
include ("../functions/functions.output.php");

function remove_directory_recursive($dir) {
    if (!is_dir($dir)) {
        return;
    }

    $items = scandir($dir);

    foreach ($items as $item) {
        if ($item == "." || $item == "..") {
            continue;
        }

        $path = $dir . DIRECTORY_SEPARATOR . $item;

        if (is_dir($path)) {
            remove_directory_recursive($path);
        } else {
            @unlink($path);
        }
    }

    @rmdir($dir);
}

function generate_filled_pdf_zip($qid,$add_scan) {
    global $db;

    $qid = intval($qid);
    $add_scan = boolval($add_scan);

    $questionnaire = $db->GetRow("
        SELECT qid, quexf_pdf
        FROM questionnaires
        WHERE qid = '$qid'
    ");

    if (empty($questionnaire)) {
        return array("success" => false, "message" => "Questionnaire not found");
    }

    $xmlbanding = export_banding($qid,false);

    if (empty($questionnaire['quexf_pdf']) || empty($xmlbanding)) {
        return array("success" => false, "message" => "The PDF, queXML, or banding file is missing from the database");
    }

    $tmpBase = rtrim(TEMPORARY_DIRECTORY, DIRECTORY_SEPARATOR);
    $tmpDir = $tmpBase . DIRECTORY_SEPARATOR . "qid_" . $qid;
    $runDir = $tmpDir . DIRECTORY_SEPARATOR . uniqid("filled_pdf_", true);
    $outDir = $runDir . DIRECTORY_SEPARATOR . "pdf";
    $pdfPath = $runDir . DIRECTORY_SEPARATOR . "quexmlpdf_" . $qid . ".pdf";
    $bandingPath = $runDir . DIRECTORY_SEPARATOR . "quexf_banding_" . $qid . ".xml";
    $zipPath = $tmpDir . DIRECTORY_SEPARATOR . "filled_pdfs_qid_" . $qid . ".zip";

    if (!mkdir($outDir, 0700, true) && !is_dir($outDir)) {
        return array("success" => false, "message" => "Unable to create temporary directory");
    }

    if (file_put_contents($pdfPath, $questionnaire['quexf_pdf']) === false) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "Unable to write temporary PDF");
    }

    if (file_put_contents($bandingPath, $xmlbanding) === false) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "Unable to write temporary banding file");
    }

    $script = realpath(dirname(__FILE__) . "/../py/queXF_FillPDFGenerator.py");

    if ($script === false) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "Python script not found");
    }

    $command = PYVENV. "/bin/python3 -u " . escapeshellarg($script)
        . " " . escapeshellarg($qid)
        . " --db-host " . escapeshellarg(DB_HOST)
        . " --db-user " . escapeshellarg(DB_USER)
        . " --db-password " . escapeshellarg(DB_PASS)
        . " --db-name " . escapeshellarg(DB_NAME)
        . " --pdf " . escapeshellarg($pdfPath)
        . " --banding " . escapeshellarg($bandingPath)
        . " --out " . escapeshellarg($outDir);
    if ($add_scan) {
        $command .= " --add-scanned";
    }

    $returnCode = 0;
    passthru($command, $returnCode);

    if ($returnCode !== 0) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "Error during PDF generation");
    }

    $pdfFiles = glob($outDir . DIRECTORY_SEPARATOR . "*.pdf");

    if (empty($pdfFiles)) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "No PDF was generated");
    }

    $zip = new ZipArchive();

    if ($zip->open($zipPath, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "Unable to create the ZIP file");
    }

    foreach ($pdfFiles as $pdfFile) {
        $zip->addFile($pdfFile, basename($pdfFile));
    }

    $zip->close();

    if (!file_exists($zipPath)) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "The ZIP file was not generated");
    }

    // Prepare the download URL
    $downloadUrl = "download_zip.php?qid=" . $qid;

    // Clean up temporary files
    remove_directory_recursive($runDir);

    return array("success" => true, "downloadUrl" => $downloadUrl);
}

?>
