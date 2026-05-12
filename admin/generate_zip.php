<?php
include_once("../config.inc.php");
include_once("../db.inc.php");

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

function generate_filled_pdf_zip($qid) {
    global $db;

    $qid = intval($qid);

    $questionnaire = $db->GetRow("
        SELECT qid, quexf_pdf, quexf_banding
        FROM questionnaires
        WHERE qid = '$qid'
    ");

    if (empty($questionnaire)) {
        return array("success" => false, "message" => "Questionnaire not found");
    }

    if (empty($questionnaire['quexf_pdf']) || empty($questionnaire['quexf_banding'])) {
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

    if (file_put_contents($bandingPath, $questionnaire['quexf_banding']) === false) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "Unable to write temporary banding file");
    }

    $script = realpath(dirname(__FILE__) . "/../py/queXF_FillPDFGenerator.py");

    if ($script === false) {
        remove_directory_recursive($runDir);
        return array("success" => false, "message" => "Python script not found");
    }

    $command = PYVENV. "/bin/python3 " . escapeshellarg($script)
        . " " . escapeshellarg($qid)
        . " --db-host " . escapeshellarg(DB_HOST)
        . " --db-user " . escapeshellarg(DB_USER)
        . " --db-password " . escapeshellarg(DB_PASS)
        . " --db-name " . escapeshellarg(DB_NAME)
        . " --pdf " . escapeshellarg($pdfPath)
        . " --banding " . escapeshellarg($bandingPath)
        . " --out " . escapeshellarg($outDir)
        . " 2>&1";

    $output = array();
    $returnCode = 0;
    exec($command, $output, $returnCode);

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

if (isset($_POST['qid'])) {
    $response = generate_filled_pdf_zip(intval($_POST['qid']));
    header('Content-Type: application/json');
    echo json_encode($response);
    exit();
}
?>