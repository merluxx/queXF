<?php
include_once("../config.inc.php");
include_once("../db.inc.php");

function download_filled_pdf_zip($qid) {
    global $db;

    $qid = intval($qid);

    // Assuming you have a way to map qid to zip filename or directory
    // Here, we assume the ZIP is stored in a fixed location based on qid
    $tmpBase = rtrim(TEMPORARY_DIRECTORY, DIRECTORY_SEPARATOR);
    $tmpDir = $tmpBase . DIRECTORY_SEPARATOR . "qid_" . $qid;
    $zipPath = $tmpDir . DIRECTORY_SEPARATOR . "filled_pdfs_qid_" . $qid . ".zip";

    $zipFiles = glob($zipPath);

    if (empty($zipFiles)) {
        header("HTTP/1.1 404 Not Found");
        print "ZIP file not found";
        exit();
    }

    $zipFile = $zipFiles[0];

    // Serve the file
    header('Content-Type: application/zip');
    header('Content-Disposition: attachment; filename="filled_pdfs_qid_' . $qid . '.zip"');
    readfile($zipFile);
    exit();
}

if (isset($_GET['qid'])) {
    download_filled_pdf_zip(intval($_GET['qid']));
    exit();
}
?>