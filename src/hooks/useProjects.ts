import { useEffect, useState } from "react";
import {
  createProject as createProjectRequest,
  listProjects,
  updateProjectStage,
} from "../lib/api";
import type { Project, ProjectStage } from "../types";

interface NewProjectInput {
  name: string;
  description: string;
}

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    listProjects()
      .then((loadedProjects) => {
        if (!active) return;
        setProjects(loadedProjects);
        setCurrentProjectId(loadedProjects[0]?.id ?? "");
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "无法连接本地服务");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const currentProject = projects.find((project) => project.id === currentProjectId) ?? projects[0];

  const createProject = async ({ name, description }: NewProjectInput) => {
    const project = await createProjectRequest({ name, description });
    setProjects((current) => [project, ...current]);
    setCurrentProjectId(project.id);
    return project;
  };

  const updateStage = async (stage: ProjectStage) => {
    if (!currentProject) return;
    const updatedProject = await updateProjectStage(currentProject.id, stage);
    setProjects((current) =>
      current.map((project) =>
        project.id === updatedProject.id ? updatedProject : project,
      ),
    );
  };

  return {
    projects,
    currentProject,
    loading,
    error,
    createProject,
    selectProject: setCurrentProjectId,
    updateStage,
  };
}
